"""A shot's grade: its own balance, then the one locked look, plus halation around light sources.

The look is a single film-print LUT baked by spektrafilm (Kodak Vision3 250D printed on 2393; ACEScct in, Rec.709 out); no shot changes it. What varies by
shot is only its balance, computed from the sidecar's `measured` section each time and never stored: neutralize the
measured white balance and bring the shot's average exposure to TARGET_STOPS. For each shot two LUTs are written from
camera code values: the picture, and the halation source (scene light HALATION_FROM_STOPS above the shot's average, which the render blurs,
tints and screens back over the picture).
"""
from functools import cache
from pathlib import Path

import numpy as np

from . import color

LOOKS = Path(__file__).resolve().parent.parent / "looks"
LOOK = LOOKS / "vision3-250d_2393.cube"
SIZE = 33
TARGET_STOPS = -0.15  # log-average scene luminance relative to 18% grey; a touch low-key
FACE_SHOT = 0.2  # a face at least this share of the frame height, in at least half the samples, makes a face shot
FACE_LIFT = 1.0  # most a face shot's exposure moves to put its person at their skin level
CONTRAST = 1.12  # slope in ACEScct about 18% grey before the film: a harder negative
PRINT_WHITE = 0.96  # display level the print's white is lifted to (it tops out near 0.87); None leaves the print alone
HALATION_FROM_STOPS = 3.5  # above the shot's average: lamps, softboxes, speculars glow; white paper and shirts don't
HALATION_SCALE = 64  # the glow source is stored as light / 64 so 16 bits hold it
HALATION = 1.0
HALATION_TINT = np.array([1.0, 0.32, 0.08])  # light scattered back through the red-sensitive layer


def exposure(sc: dict) -> tuple[float, float]:
    """Stops to apply: to bring the frame's average to TARGET_STOPS, and the extra for a face shot.

    In a face shot of someone with a skin level in people.json, exposure moves so their lit cheek sits at that level,
    so each person looks the same in every shot, against a bright window or not. Nobody else's face is moved: the
    machine cannot tell darker skin from underexposure, so it never brightens a face it has no level for.
    """
    measured = sc["measured"]
    stops = TARGET_STOPS - measured["exposure_stops"]
    face, skin = measured.get("face"), (sc.get("person") or {}).get("skin_stops")
    if skin is None or not (face and face["height"] >= FACE_SHOT and face["in_frames"] * 2 >= face["of"]):
        return stops, 0.0
    return stops, float(np.clip(skin - (face["key_stops"] + stops), -FACE_LIFT, FACE_LIFT))


def balance(sc: dict) -> np.ndarray:
    """Per-channel gain in scene-linear Rec.709: white balance times exposure."""
    neutral = np.array(sc["measured"]["neutral_rgb"])
    wb = neutral[1] / neutral
    wb /= color.luminance(wb)  # white balance alone must not change brightness
    return wb * 2.0 ** sum(exposure(sc))


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


def write_cube(path: Path, values: np.ndarray) -> Path:
    with open(path, "w") as f:
        f.write(f"LUT_3D_SIZE {SIZE}\n")
        np.savetxt(f, values, fmt="%.6f")
    return path


def write_luts(sc: dict, folder: Path, tag: str, look: Path = LOOK) -> tuple[Path, Path]:
    """This shot's picture LUT and halation-source LUT, both taking the camera's code values."""
    grid = np.linspace(0, 1, SIZE)
    b, g, r = np.meshgrid(grid, grid, grid, indexing="ij")  # .cube order: red changes fastest
    lin = color.to_linear_709(np.stack([r, g, b], axis=-1).reshape(-1, 3), sc["assumed"]) * balance(sc)
    pivot = color.to_acescct(np.full(3, 0.18))[0]
    picture = sample(read_cube(look), pivot + (color.to_acescct(lin) - pivot) * CONTRAST)
    if PRINT_WHITE:  # lift only the top of the print toward PRINT_WHITE; mid-tones and blacks stay where the film put them
        white = read_cube(look)[-1, -1, -1].mean()
        s = np.clip((picture - 0.5) / (white - 0.5), 0, 1)
        picture = picture + s * s * (PRINT_WHITE - white)
    # The glow belongs to how bright the scene was, so printing a face shot brighter doesn't make white shirts glow.
    threshold = 0.18 * 2 ** (TARGET_STOPS + HALATION_FROM_STOPS + exposure(sc)[1])
    source = np.maximum(color.luminance(lin) - threshold, 0) / HALATION_SCALE
    return (write_cube(folder / f"{tag}.cube", picture),
            write_cube(folder / f"{tag}-halation.cube", np.repeat(np.minimum(source, 1)[:, None], 3, axis=1)))


def write_glow(folder: Path) -> tuple[Path, Path, Path]:
    """1D LUTs for adding the glow as light: blurred source to glow, and display Rec.709 to and from linear display light.

    The print maps 18% grey to about 17% display light, so light added on the display side lands close to where the
    same light added to the negative would."""
    def write(name: str, values: np.ndarray) -> Path:
        path = folder / name
        with open(path, "w") as f:
            f.write(f"LUT_1D_SIZE {len(values)}\n")
            np.savetxt(f, values, fmt="%.7f")
        return path
    x = np.linspace(0, 1, 65536)[:, None] * np.ones(3)
    glow = np.minimum(HALATION * HALATION_SCALE * np.linspace(0, 1, 4096)[:, None] * HALATION_TINT, 1)
    return write("glow.cube", glow), write("decode.cube", x ** 2.4), write("encode.cube", x ** (1 / 2.4))
