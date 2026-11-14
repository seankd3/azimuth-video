"""App acceptance, on synthetic clips. Run it as tests/headless.sh .venv/bin/python tests/app.py

1. The door. Random actions, the way a person and an agent mix them (split, trim past either end, move, remove, add,
   frame, aspect, look, undo, redo, a write from outside). After each, the file holds exactly the current history
   entry, every shot the door wrote lies inside its source and lasts at least a frame with every framing what
   view.frame makes of it (a file from outside is shown and rendered through view.frame as it is, and made valid by
   the next change), and undo then redo comes back to the same edit.
2. The window, in a headless compositor on the GPU. After random edits through the window's own calls, its view of the
   edit equals a freshly opened window's on the same file, and playing across a cut hands over to the other deck and
   keeps going.
"""
import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import opentimelineio as otio  # noqa: E402

from footage import sidecar, view  # noqa: E402
from footage.app import edit as E  # noqa: E402

SEED = int(os.environ.get("SEED", 1))


def clips(folder: Path) -> list[Path]:
    """Three 4-second clips: a plain one, an anamorphic one and a short tall one."""
    out = []
    for name, (w, h, squeeze, hue) in {"A": (640, 360, 1.0, 0), "B": (640, 360, 1.6, 120), "C": (360, 640, 1.0, 240)}.items():
        p = folder / f"{name}.MP4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=30:duration=4",
                        "-vf", f"hue=h={hue}", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p)], check=True)
        sidecar.write(p, {"facts": {"original_name": p.name, "sha256": "0" * 64, "size": p.stat().st_size,
                                    "duration": 4.0, "fps": "30/1", "width": w, "height": h, "pix_fmt": "yuv420p",
                                    "color_range": "tv"}, "assumed": {"squeeze": squeeze}})
        out.append(p)
    return out


def actions(rng: random.Random, t: otio.schema.Timeline, sources: list[Path]):
    """One random action for the current edit: (function, args)."""
    n = len(E.picture(t))
    i = rng.randrange(n)
    return rng.choice([
        (E.split, (i, rng.uniform(-1, 5))),
        (E.trim, (i, rng.uniform(-2, 4), rng.uniform(-1, 6))),
        (E.move, (i, rng.randrange(n))),
        (E.remove, (i,)) if n > 1 else (E.move, (i, i)),
        (E.add, (rng.randrange(n + 1), str(rng.choice(sources)), rng.uniform(0, 3), rng.uniform(0.2, 2))),
        (E.frame, (i, {"turn": rng.randrange(-2, 6), "zoom": rng.uniform(0.5, 10),
                       "center": [rng.uniform(-0.5, 1.5), rng.uniform(-0.5, 1.5)]})),
        (E.setting, ("aspect", rng.choice([v for _, v in E.ASPECTS]))),
        (E.setting, ("look", rng.choice(["cinema-glow", "natural", "portra-400"]))),
    ])


def problems(e: E.Edit, outside: set) -> list[str]:
    found = []
    on_disk = E.text(otio.adapters.read_from_file(str(e.path)))
    if on_disk != e.history[e.at]:
        found.append("the file is not the current history entry")
    if e.history[e.at] in outside:
        return found
    t, a = e.timeline, E.aspect(e.timeline)
    for k, c in enumerate(E.picture(t)):
        sc = E.facts(E.media(c))
        start, d = c.source_range.start_time.to_seconds(), c.source_range.duration.to_seconds()
        if start < -1e-6 or start + d > sc["facts"]["duration"] + 1e-6 or d < 1 / 30 - 1e-6:
            found.append(f"shot {k} runs {start:.3f}+{d:.3f} outside its {sc['facts']['duration']} s source")
        f = c.metadata.get("footage", {}).get("framing")
        f = f and {k: list(v) if k == "center" else v for k, v in f.items()}
        if f is not None and f != view.frame(sc, f, a):
            found.append(f"shot {k} stores an invalid framing {dict(f)}")
    return found


def door(folder: Path, sources: list[Path], steps: int = 300) -> int:
    rng = random.Random(SEED)
    e = E.Edit(folder / "door.otio", E.new(sources))
    bad, outside = 0, set()
    for step in range(steps):
        roll = rng.random()
        if roll < 0.1:
            label = "undo"
            e.undo()
        elif roll < 0.15:
            label = "redo"
            e.redo()
        elif roll < 0.2:  # an agent rewrites the file: reorder its shots and rename it
            label = "outside write"
            t = otio.adapters.read_from_file(str(e.path))
            track = E.picture(t)
            first = track[0]
            del track[0]
            track.append(first)
            t.name = f"agent {step}"
            otio.adapters.write_to_file(t, str(e.path))
            if not e.outside():
                print(f"FAIL step {step}: an outside write was not read in")
                bad += 1
            outside.add(e.history[e.at])
        else:
            fn, args = actions(rng, e.timeline, sources)
            label = f"{fn.__name__}{args}"
            e.do(fn, *args)
        here = e.history[e.at]
        if e.undo():
            e.redo()
            if e.history[e.at] != here:
                bad += 1
                print(f"FAIL step {step}: undo then redo changed the edit")
        for p in problems(e, outside):
            bad += 1
            print(f"FAIL step {step} after {label}: {p}")
    print(f"{'FAIL' if bad else 'PASS'} the door: {steps} random actions, the file is always the history and every "
          f"shot and framing valid ({bad} problems)")
    return bad


def window(folder: Path, sources: list[Path]) -> int:
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext

    from footage.app import __main__ as M
    from footage.app.backend import Backend, Images, Theme

    _app = QGuiApplication.instance() or QGuiApplication([])  # held: Qt needs it alive

    def wait(seconds: float):
        loop = QEventLoop()
        QTimer.singleShot(int(seconds * 1000), loop.quit)
        loop.exec()

    def open_window(path: Path):
        backend = Backend(Theme())
        engine = QQmlApplicationEngine()
        engine.addImageProvider("av", Images())
        engine.rootContext().setContextProperty("backend", backend)
        engine.rootContext().setContextProperty("lutShader", M.shader())
        engine.load(M.HERE / "Main.qml")
        backend.open(str(path))
        return engine, backend, engine.rootObjects()[0]

    def js(win, text):
        return QQmlExpression(qmlContext(win), win, text).evaluate()[0]

    bad = 0
    # A gap in an agent's edit: the window names shots by their place among the shots, the track counts the gap too.
    gapped = folder / "gap.otio"
    t = E.new(sources)
    E.picture(t).insert(1, otio.schema.Gap(source_range=otio.opentime.TimeRange(duration=otio.opentime.RationalTime(30, 30))))
    E.Edit(gapped, t)
    engine, backend, win = open_window(gapped)
    backend.remove(1)
    after = otio.adapters.read_from_file(str(gapped))  # held: a track dies with its timeline
    kinds = [type(c).__name__ + (f" {c.name}" if isinstance(c, otio.schema.Clip) else "") for c in E.picture(after)]
    ok = kinds == ["Clip A", "Gap", "Clip C"]
    bad += not ok
    print(f"{'PASS' if ok else 'FAIL'} removing the second shot of an edit with a gap removes that shot: {kinds}")
    win.close()
    del engine

    path = folder / "window.otio"
    E.Edit(path, E.new(sources))
    engine, backend, win = open_window(path)
    rng = random.Random(SEED + 1)
    for _ in range(40):
        n = len(backend.shots)
        i = rng.randrange(n)
        rng.choice([lambda: backend.split(i, rng.uniform(0.2, 1.5)),
                    lambda: backend.trim(i, rng.uniform(0, 1), rng.uniform(2, 4)),
                    lambda: backend.move(i, rng.randrange(n)),
                    lambda: backend.remove(i) if n > 2 else None,
                    lambda: backend.setFraming(i, {"turn": rng.randrange(4), "zoom": rng.uniform(1, 3),
                                                   "center": [rng.random(), rng.random()]}),
                    lambda: backend.setAspect(rng.choice(backend.aspects)),
                    lambda: backend.undo()])()
    wait(0.5)
    live = json.loads(js(win, "JSON.stringify(win.shots)"))
    _, fresh_backend, fresh = open_window(path)
    wait(0.5)
    again = json.loads(js(fresh, "JSON.stringify(win.shots)"))
    same = live == again
    bad += not same
    print(f"{'PASS' if same else 'FAIL'} the window's view after 40 edits equals a fresh window's on the same file")
    fresh.close()

    # Playback across a cut: a shot plays out and the other deck takes over, into a shot long enough to see it play.
    if not any(b["duration"] >= 1.5 for b in live[1:]):
        backend.add(len(live), str(sources[0]))
        wait(0.3)
        live = json.loads(js(win, "JSON.stringify(win.shots)"))
    i = next(k for k in range(len(live) - 1) if live[k + 1]["duration"] >= 1.5)
    cut = live[i + 1]["at"]
    win.seek(max(cut - 0.6, live[i]["at"]))
    wait(0.8)
    before = js(win, "win.active")
    win.play()
    wait(1.4)
    after, playhead, now = js(win, "win.active"), js(win, "win.playhead"), js(win, "win.current")
    win.pause()
    crossed = before != after and now == i + 1 and playhead > cut + 0.3
    bad += not crossed
    print(f"{'PASS' if crossed else 'FAIL'} playback crosses the cut at {cut:.2f} s onto the other deck "
          f"(deck {before} to {after}, shot {i} to {now}, playhead {playhead:.2f} s)")
    win.close()
    del engine
    return bad


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "edits"
        folder.mkdir()
        sources = clips(Path(tmp))
        bad = door(folder, sources)
        if os.environ.get("AZIMUTH_HEADLESS") == os.environ.get("WAYLAND_DISPLAY", "-"):
            bad += window(folder, sources)
        else:  # never on the desktop: only in the compositor headless.sh starts
            print("SKIP the window: run under tests/headless.sh")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
