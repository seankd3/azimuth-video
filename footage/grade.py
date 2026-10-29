"""A shot's grade: its own balance, then the edit's look, plus halation around light sources.

A look is a named print, `looks/NAME.json`: a film-print LUT baked by spektrafilm (ACEScct in, Rec.709 out) and how it
is printed (contrast, warmth, black and white levels, halation, vignette). One look covers a whole edit, so every shot
is printed the same way. What varies by shot is only its balance, computed from the sidecar's `measured` section each
time and never stored: neutralize the measured white balance and bring the shot's average exposure to the look's.
For each shot two LUTs are written from camera code values: the picture, and the halation source (tinted scene light
some stops above the shot's average, which the render blurs and adds back over the picture as light).

python -m footage.grade  lists the looks.
"""
import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np

from . import color, config

LOOKS = Path(__file__).resolve().parent.parent / "looks"
DEFAULT = config.load().get("look", "cinema")  # the house look: a timeline's own look or --look overrides it
SIZE = 33
FACE_SHOT = 0.2  # a face at least this share of the frame height, in at least half the samples, makes a face shot
FACE_LIFT = 1.0  # most a face shot's exposure moves to put its person at their skin level
HALATION_SCALE = 64  # the glow source is stored as light / 64 so 16 bits hold it


@dataclass(frozen=True)
class Look:
    name: str
    about: str
    lut: Path
    exposure: float = -0.15  # log-average scene luminance relative to 18% grey; below 0 is low-key
    contrast: float = 1.0  # slope in ACEScct about 18% grey before the film: above 1 is a harder negative
    warmth: float = 0.0  # stops of red over blue in the scene light before the film: below 0 is cooler
    black: float | None = None  # display level the print's black is moved to; None leaves the print's own
    white: float | None = None  # display level the print's white is moved to (prints top out near 0.87)
    halation: float = 0.0  # how much light scatters back through the red-sensitive layer
    halation_tint: tuple[float, float, float] = (1.0, 0.32, 0.08)
    halation_from: float = 3.5  # stops above the shot's average: lamps and speculars glow; white shirts don't
    halation_spread: float = 1.0  # glow radius relative to the default
    vignette: float = 0.0  # stops darker in the corners, as lens falloff


@cache
def look(name: str = DEFAULT) -> Look:
    """The look in looks/NAME.json; an unknown setting in the file is an error, not ignored."""
    fields = json.loads((LOOKS / f"{name}.json").read_text())
    return Look(name=name, **{**fields, "lut": LOOKS / fields["lut"],
                              "halation_tint": tuple(fields.get("halation_tint", Look.halation_tint))})


def looks() -> list[Look]:
    return [look(p.stem) for p in sorted(LOOKS.glob("*.json"))]


def exposure(sc: dict, look: Look) -> tuple[float, float]:
    """Stops to apply: to bring the frame's average to the look's exposure, and the extra for a face shot.

    In a face shot of someone with a skin level in people.json, exposure moves so their lit cheek sits at that level,
    so each person looks the same in every shot, against a bright window or not. Nobody else's face is moved: the
    machine cannot tell darker skin from underexposure, so it never brightens a face it has no level for.
    """
    measured = sc["measured"]
    stops = look.exposure - measured["exposure_stops"]
    face, skin = measured.get("face"), (sc.get("person") or {}).get("skin_stops")
    if skin is None or not (face and face["height"] >= FACE_SHOT and face["in_frames"] * 2 >= face["of"]):
        return stops, 0.0
    return stops, float(np.clip(skin - (face["key_stops"] + stops), -FACE_LIFT, FACE_LIFT))


def balance(sc: dict, look: Look) -> np.ndarray:
    """Per-channel gain in scene-linear Rec.709: white balance to the look's warmth, times exposure."""
    neutral = np.array(sc["assumed"].get("neutral_rgb") or sc["measured"]["neutral_rgb"])  # a hand-set neutral wins
    wb = neutral[1] / neutral * 2.0 ** (look.warmth * np.array([0.5, 0, -0.5]))
    wb /= color.luminance(wb)  # white balance alone must not change brightness
    return wb * 2.0 ** sum(exposure(sc, look))


@cache
def read_cube(path: Path) -> np.ndarray:
    rows = [line.split() for line in open(path) if line[:1] in "-.0123456789" and len(line.split()) == 3]
    n = round(len(rows) ** (1 / 3))
    return np.array(rows, dtype=np.float32).reshape(n, n, n, 3)  # [blue][green][red]


def sample(lut: np.ndarray, rgb: np.ndarray) -> np.ndarray:
    """Trilinear lookup of RGB values in 0..1."""
    n = lut.shape[0]
    f = np.clip(rgb, 0, 1) * (n - 1)
    i = np.minimum(f.astype(int), n - 2)
    t = f - i
    out = 0
    for db in (0, 1):
        for dg in (0, 1):
            for dr in (0, 1):
                wgt = (t[..., 2] if db else 1 - t[..., 2]) * (t[..., 1] if dg else 1 - t[..., 1]) * (t[..., 0] if dr else 1 - t[..., 0])
                out = out + wgt[..., None] * lut[i[..., 2] + db, i[..., 1] + dg, i[..., 0] + dr]
    return out


@cache
def grey_axis(look: Path) -> list[tuple[np.ndarray, np.ndarray]]:
    """Per-channel curves that make the look's greys neutral: like timing a print, so grey stays grey at every level.

    A print emulation doesn't map grey to grey (this one goes green in the shadows, yellow-green in the highlights).
    Each output channel is remapped so that, along the grey axis, it equals the grey's luminance; the film's contrast,
    colour density and colour rendering stay as they are."""
    x = np.linspace(0, 1, 2048)
    grey = sample(read_cube(look), np.repeat(x[:, None], 3, axis=1))
    target = color.luminance(grey)
    return [(np.maximum.accumulate(grey[:, c]), target) for c in range(3)]


def write_cube(path: Path, values: np.ndarray) -> Path:
    with open(path, "w") as f:
        f.write(f"LUT_3D_SIZE {SIZE}\n")
        np.savetxt(f, values, fmt="%.6f")
    return path


def write_luts(sc: dict, folder: Path, tag: str, look: Look) -> tuple[Path, Path]:
    """This shot's picture LUT and halation-source LUT, both taking the camera's code values."""
    grid = np.linspace(0, 1, SIZE)
    b, g, r = np.meshgrid(grid, grid, grid, indexing="ij")  # .cube order: red changes fastest
    lin = color.to_linear_709(np.stack([r, g, b], axis=-1).reshape(-1, 3), sc["assumed"]) * balance(sc, look)
    pivot = color.to_acescct(np.full(3, 0.18))[0]
    picture = sample(read_cube(look.lut), pivot + (color.to_acescct(lin) - pivot) * look.contrast)
    picture = np.stack([np.interp(picture[:, c], *grey_axis(look.lut)[c]) for c in range(3)], axis=-1)
    # Move only the ends of the print: the top toward the look's white, the bottom toward its black; mid-tones stay.
    ends = grey_axis(look.lut)[0][1]  # the timed print's black and white
    black, white = ends[0], ends[-1]
    if look.white is not None:
        s = np.clip((picture - 0.5) / (white - 0.5), 0, 1)
        picture = picture + s * s * (look.white - white)
    if look.black is not None:
        s = np.clip((0.5 - picture) / (0.5 - black), 0, 1)
        picture = picture + s * s * (look.black - black)
    # The glow belongs to how bright the scene was, so printing a face shot brighter doesn't make white shirts glow.
    threshold = 0.18 * 2 ** (look.exposure + look.halation_from + exposure(sc, look)[1])
    source = np.maximum(color.luminance(lin) - threshold, 0) / HALATION_SCALE
    return (write_cube(folder / f"{tag}.cube", picture),
            write_cube(folder / f"{tag}-halation.cube", np.repeat(np.minimum(source, 1)[:, None], 3, axis=1)))


def write_glow(folder: Path, look: Look) -> tuple[Path, Path, Path]:
    """1D LUTs for adding the glow as light: blurred source to the look's tinted glow, and display Rec.709 to and from
    linear display light. The tint is applied here, after the blur, so the dim skirt of a blue-poor glow keeps 16-bit steps.

    The print maps 18% grey to about 17% display light, so light added on the display side lands close to where the
    same light added to the negative would."""
    def write(name: str, values: np.ndarray) -> Path:
        path = folder / name
        with open(path, "w") as f:
            f.write(f"LUT_1D_SIZE {len(values)}\n")
            np.savetxt(f, values, fmt="%.7f")
        return path
    x = np.linspace(0, 1, 65536)[:, None] * np.ones(3)
    glow = np.minimum(look.halation * HALATION_SCALE * np.linspace(0, 1, 4096)[:, None] * np.array(look.halation_tint), 1)
    return write("glow.cube", glow), write("decode.cube", x ** 2.4), write("encode.cube", x ** (1 / 2.4))


def write_vignette(path: Path, size: tuple[int, int], look: Look) -> Path:
    """A 16-bit mask of lens falloff: cos^4 of the distance from the centre, the corners look.vignette stops darker."""
    import cv2
    w, h = size
    y, x = np.ogrid[:h, :w]
    d = np.hypot(x - w / 2, y - h / 2) / np.hypot(w / 2, h / 2)
    cv2.imwrite(str(path), np.round(np.cos(np.arccos(2 ** (-look.vignette / 4)) * d) ** 4 * 65535).astype(np.uint16))
    return path


if __name__ == "__main__":
    for lk in looks():
        print(f"{lk.name:24} {lk.about}")
