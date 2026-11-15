"""Framing acceptance: a shot shows the part of its frame view.window says, turned the way it says, in every aspect.

A synthetic clip holds one white square at a known recorded pixel. For each squeeze, turn, aspect and framing, the
shot is decoded through render.decode (the GPU path a render takes) and brought to the master's size the way
picture.Shot does. The square must land where an independent forward turn of its position puts it, within the
rounding of one recorded pixel. A wrong turn direction, a squeeze applied on the wrong axis or a crop placed
before the turn would each move it across the frame. A clip whose camera was held on its side (its recorded roll)
must come out upright with no framing at all, in a master as tall as the clip stands: a vertical clip once rendered
sideways until a person turned it by hand. Also: the door (view.frame) is idempotent and keeps every
window inside its frame, whatever it is given.

Run inside the GPU lane: heavy -w framing-test .venv/bin/python tests/framing.py
"""
import itertools
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from footage import picture, render, view  # noqa: E402

W, H, BOX = 1280, 720, 8
MARK = (900, 200)  # the square's top-left, in recorded pixels: off centre on both axes


def clip(folder: Path) -> Path:
    out = folder / "T.MP4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=black:s={W}x{H}:r=30:d=1",
                    "-vf", f"drawbox=x={MARK[0]}:y={MARK[1]}:w={BOX}:h={BOX}:color=white:t=fill",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-color_range", "tv", str(out)], check=True)
    return out


def sidecar(squeeze: float, roll: float | None = None) -> dict:
    return {"facts": {"original_name": "T.MP4", "width": W, "height": H, "fps": "30/1", "pix_fmt": "yuv420p",
                      "color_range": "tv", "notes": {"roll": roll}}, "assumed": {"squeeze": squeeze}}


def expected(sc: dict, framing: dict, aspect: float, size: tuple[int, int]) -> tuple[float, float]:
    """Where the square's centre lands in the master: turned forward, clockwise, one quarter turn at a time."""
    f, s = view.frame(sc, framing, aspect), view.squeeze(sc)
    x, y, fw, fh = (MARK[0] + BOX / 2) * s, MARK[1] + BOX / 2, W * s, H
    for _ in range(f["turn"]):
        x, y, fw, fh = fh - y, x, fh, fw
    w, h = view.fitted(sc, f["turn"], aspect, f["zoom"])
    x0, y0 = f["center"][0] * fw - w / 2, f["center"][1] * fh - h / 2
    return (x - x0) / w * size[0], (y - y0) / h * size[1]


def measured(clip: Path, sc: dict, framing: dict, aspect: float, size: tuple[int, int]) -> tuple[float, float]:
    import torch
    win = view.window(sc, framing, aspect)
    code = next(iter(render.decode(clip, sc, 0, 1, "", win)))
    shown = picture.resize(code, picture.resampler(code.shape[2], size[0]), picture.resampler(code.shape[1], size[1]))
    ys, xs = torch.nonzero(shown[1] > 0.5, as_tuple=True)
    return xs.float().mean().item() + 0.5, ys.float().mean().item() + 0.5


def main() -> int:
    failed = checked = 0
    with tempfile.TemporaryDirectory() as tmp:
        c = clip(Path(tmp))
        framings = [{}, {"zoom": 2.0, "center": [0.65, 0.3]}, {"zoom": 1.5, "center": [0.6, 0.45]}]
        for squeeze, turn, aspect, base in itertools.product((1.0, 1.6), range(4), (2.39, 16 / 9, 9 / 16, 1.0), framings):
            sc, framing = sidecar(squeeze), {**base, "turn": turn}
            size = view.master([sc], aspect)
            win = view.window(sc, framing, aspect)
            ex, ey = expected(sc, framing, aspect, size)
            if not (0 <= ex < size[0] and 0 <= ey < size[1]):
                continue  # this framing leaves the square out of the window
            mx, my = measured(c, sc, framing, aspect, size)
            across, down = (win.h, win.w) if turn % 2 else (win.w, win.h)  # recorded pixels across and down the master
            tol = 1 + 1.5 * max(size[0] / across, size[1] / down)  # a recorded pixel of rounding, in the master
            ok = abs(mx - ex) <= tol and abs(my - ey) <= tol
            failed, checked = failed + (not ok), checked + 1
            if not ok:
                print(f"FAIL squeeze {squeeze} turn {turn} aspect {aspect:.3f} {base}: square at ({mx:.1f}, {my:.1f}),"
                      f" expected ({ex:.1f}, {ey:.1f}) in {size[0]}x{size[1]}")
        print(f"{'FAIL' if failed else 'PASS'} the square lands where the framing puts it ({failed} of {checked} misplaced)")

        # Held on its side: -91.4 is a camera turned a quarter clockwise as its level sensor recorded it, so the
        # picture turns back three quarters; 88 the other way, 179 upside down, a 3 degree tilt not at all.
        sideways = 0
        for roll, turn in ((-91.4, 3), (88.0, 1), (179.0, 2), (-3.0, 0), (None, 0)):
            sc = sidecar(1.0, roll)
            aspect = view.aspect(None, [sc])
            size = view.master([sc], aspect)
            ex, ey = expected(sc, {}, aspect, size)
            mx, my = measured(c, sc, {}, aspect, size)
            portrait = size[1] > size[0]
            ok = view.window(sc, None, aspect).turn == turn and portrait == bool(turn % 2) and \
                abs(mx - ex) <= 2.5 and abs(my - ey) <= 2.5
            sideways += not ok
            if not ok:
                print(f"FAIL roll {roll}: turn {view.window(sc, None, aspect).turn}, master {size}, square at "
                      f"({mx:.1f}, {my:.1f}), expected ({ex:.1f}, {ey:.1f})")
        print(f"{'FAIL' if sideways else 'PASS'} a clip held on its side comes out upright unframed ({sideways} wrong)")
        failed += sideways

    door = 0
    for squeeze, turn, aspect, zoom, cx, cy in itertools.product((1.0, 1.6), (-1, 0, 1, 2, 7), (2.39, 9 / 16, 1.0),
                                                                  (0.2, 1, 3, 20), (-1, 0, 0.5, 1, 2), (-1, 0.5, 2)):
        sc = sidecar(squeeze)
        f = view.frame(sc, {"turn": turn, "zoom": zoom, "center": [cx, cy]}, aspect)
        x, y, w, h, t = view.window(sc, f, aspect)
        door += not (view.frame(sc, f, aspect) == f and 0 <= x and x + w <= W and 0 <= y and y + h <= H
                     and w > 0 and h > 0 and w % 2 == 0 and h % 2 == 0 and t == turn % 4)
    print(f"{'FAIL' if door else 'PASS'} the door is idempotent and keeps every window inside its frame ({door} bad)")
    return 1 if failed or door else 0


if __name__ == "__main__":
    sys.exit(main())
