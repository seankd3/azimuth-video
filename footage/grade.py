"""A shot's grade: its own balance, then the edit's look, plus halation around light sources.

A look is a named print, `looks/NAME.json`: a film-print LUT baked by spektrafilm (ACEScct in, Rec.709 out) and how it
is printed (contrast, warmth, black and white levels, halation, vignette). One look covers a whole edit, so every shot
is printed the same way. What varies by shot is only its balance, computed from the sidecar's `measured` section each
time and never stored: neutralize the measured white balance and bring the shot's average exposure to the look's.
For each shot the print LUT takes camera code values to the print; the halation curve takes them to how close each
pixel came to clipping, which picture.py blurs, tints and adds back over the picture as light.

python -m footage.grade  lists the looks.
"""
import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np

from . import color, config

LOOKS = Path(__file__).resolve().parent.parent / "looks"
DEFAULT = config.load().get("look", "cinema-glow")  # the house look: a timeline's own look or --look overrides it
SIZE = 33
FACE_SHOT = 0.2  # a face at least this share of the frame height, in at least half the samples, makes a face shot
FACE_LIFT = 1.0  # most a face shot's exposure moves to put its person at their skin level
WHITE = float(np.log2(0.9 / 0.18))  # diffuse white, a white wall or page, in stops above 18% grey
VIGNETTE_FLAT = 0.35  # share of the way to the corners a vignette leaves untouched
NIGHT = (0.005, 0.09)  # scene light where a night shot's colour is faded most, and where it is full again


@dataclass(frozen=True)
class Look:
    name: str
    about: str
    lut: Path
    exposure: float = -0.15  # log-average scene luminance relative to 18% grey; below 0 is low-key
    contrast: float = 1.0  # slope in ACEScct about 18% grey before the film: above 1 is a harder negative
    warmth: float = 0.0  # stops of red over blue in the scene light before the film: below 0 is cooler
    tint: float = 0.0  # stops of magenta over green in the scene light: above 0 takes out fluorescent green
    black: float | None = None  # display level the print's black is moved to; None leaves the print's own
    white: float | None = None  # display level the print's white is moved to (prints top out near 0.87)
    halation: float = 0.0  # how much light scatters back through the red-sensitive layer
    halation_tint: tuple[float, float, float] = (1.0, 0.32, 0.08)
    halation_from: float = 0.12  # stops below the camera's clipping point at which the glow starts
    halation_spread: float = 1.0  # glow radius relative to the default
    vignette: float = 0.0  # stops darker in the corners, from a flat centre
    key: float = 0.0  # how much of the scene's own key is kept: 1 keeps a bright room brighter than a dim one
    dark: float | None = None  # a dark shot (one the target would brighten) is shown as exposed, moved this many stops
    #                           (the camera was exposed for its lit part); None brightens it to the target
    night: float = 0.0  # share of colour a dark shot loses in its deepest shadows, as the eye does at night
    headroom: float | None = None  # most stops the 99th percentile may land above diffuse white; None: no limit
    shadows: float = 0.0  # share of the shadows' own grey balance applied: 1 makes grey grey at every level
    mood: float = 0.0  # stops darker for each stop of the scene's contrast (1st to 99th percentile) above mood_from:
    #                   harder light is shown moodier
    mood_from: float = 7.0  # contrast in stops at which mood starts; soft light measured about 7


@cache
def look(name: str = DEFAULT) -> Look:
    """The look in looks/NAME.json; an unknown setting in the file is an error, not ignored."""
    fields = json.loads((LOOKS / f"{name}.json").read_text())
    return Look(name=name, **{**fields, "lut": LOOKS / fields["lut"],
                              "halation_tint": tuple(fields.get("halation_tint", Look.halation_tint))})


def looks() -> list[Look]:
    return [look(p.stem) for p in sorted(LOOKS.glob("*.json"))]


def target(sc: dict, look: Look) -> float:
    """Stops that bring the frame's average to the look's exposure, keeping look.key of the scene's own key."""
    measured = sc["measured"]
    avg, (low, high) = measured["exposure_stops"], measured["range_stops"]
    # The scene's key: where its average sits in its own range of light, -1 (low-key) to 1 (high-key), as in
    # Reinhard's automatic key (2002): a key of k keeps 2k stops of the scene's brightness.
    k = 2 * (avg - low) / (high - low) - 1 if high > low else 0.0
    return look.exposure + look.key * 2 * k - avg


def dark(sc: dict, look: Look) -> bool:
    """Whether the look shows this shot as a dark one: as exposed, for its lit part, rather than brightened."""
    return look.dark is not None and target(sc, look) > 0


def exposure(sc: dict, look: Look) -> tuple[float, float]:
    """Stops to apply: to bring the frame's average to the look's exposure, darker by the look's mood for a shot with
    harder light, plus any correction a person set for the shot (footage.assume CLIP exposure=-0.3), and the extra for
    a face shot.

    In a face shot of someone with a skin level in people.json, exposure moves so their lit cheek sits at that level,
    so each person looks the same in every shot, against a bright window or not. Nobody else's face is moved: the
    machine cannot tell darker skin from underexposure, so it never brightens a face it has no level for.
    """
    measured = sc["measured"]
    stops = look.dark if dark(sc, look) else target(sc, look)  # ETTR comes down fully; a dark shot keeps its exposure
    if look.headroom is not None:  # and never so far that the brightest unclipped light goes past the shoulder
        stops = min(stops, WHITE + look.headroom - measured["range_stops"][1])
    stops -= look.mood * max(0.0, measured["range_stops"][1] - measured["range_stops"][0] - look.mood_from)
    stops += sc["assumed"].get("exposure") or 0.0
    face, skin = measured.get("face"), (sc.get("person") or {}).get("skin_stops")
    if skin is None or not (face and face["height"] >= FACE_SHOT and face["in_frames"] * 2 >= face["of"]):
        return stops, 0.0
    return stops, float(np.clip(skin - (face["key_stops"] + stops), -FACE_LIFT, FACE_LIFT))


def balance(sc: dict, look: Look) -> np.ndarray:
    """Per-channel gain in scene-linear Rec.709: white balance to the look's warmth and tint, times exposure."""
    neutral = np.array(sc["assumed"].get("neutral_rgb") or sc["measured"]["neutral_rgb"])  # a hand-set neutral wins
    wb = neutral[1] / neutral * 2.0 ** (look.warmth * np.array([0.5, 0, -0.5]) + look.tint * np.array([0.5, -0.5, 0.5]))
    wb /= color.luminance(wb)  # white balance alone must not change brightness
    return wb * 2.0 ** sum(exposure(sc, look))


def shading(sc: dict, look: Look, lin: np.ndarray) -> np.ndarray:
    """Per-pixel gain that makes the shadows' grey grey too, for scene-linear Rec.709 light before balance().

    Mixed light can tint the shade apart from the lit surfaces (fluorescent green in the shade of a warm-lit room):
    one balance can't make both grey. At and below the shadows' grey level the gain is the shadows' own balance
    relative to the main one; at and above the main grey's level it is 1; between, it blends in stops. A hand-set
    neutral, a shadow grey without evidence, or a look that keeps the shadows' tint leaves every gain 1."""
    m = sc["measured"]
    if not look.shadows or sc["assumed"].get("neutral_rgb") or m["shadow_gate"] is None or m["neutral_stops"] is None:
        return np.ones_like(lin)
    shade, white = np.array(m["shadow_rgb"]), np.array(m["neutral_rgb"])
    gain = (white / shade) ** look.shadows
    gain /= color.luminance(gain)
    lo, hi = m["shadow_stops"], m["neutral_stops"]
    s = np.log2(np.maximum(color.luminance(lin), 1e-9) / 0.18)
    t = np.clip((s - lo) / (hi - lo), 0, 1)[..., None] if hi > lo else np.ones(s.shape + (1,))
    return gain ** (1 - t)


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


def print_lut(sc: dict, look: Look) -> np.ndarray:
    """This shot's print LUT: camera code values on a SIZE^3 grid (red changing fastest, as in a .cube file) to the
    display Rec.709 print."""
    grid = np.linspace(0, 1, SIZE)
    b, g, r = np.meshgrid(grid, grid, grid, indexing="ij")
    lin = color.to_linear_709(np.stack([r, g, b], axis=-1).reshape(-1, 3), sc["assumed"])
    lin = lin * shading(sc, look, lin) * balance(sc, look)
    if look.night and dark(sc, look):  # colour fades out of the shadows of a night: a lot under green lights reads dark
        y = color.luminance(lin)[:, None]
        t = np.clip((y - NIGHT[0]) / (NIGHT[1] - NIGHT[0]), 0, 1)
        lin = y + (lin - y) * (1 - look.night * (1 - t * t * (3 - 2 * t)))
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
    return picture.astype(np.float32)


def halation(sc: dict, look: Look) -> tuple[np.ndarray, np.ndarray]:
    """This shot's halation: the glow source for each code value of a pixel's brightest channel (0..1, on 65536
    steps), and the gain per channel that takes the blurred source to the tinted light it adds (at most 1).

    A light is what the camera couldn't hold: the source is how close a pixel came to the sensor's clipping point, 0
    below the last halation_from stops and 1 at the clip, judged by its brightest channel in the camera's own light, so
    a lamp clipped in one channel counts and a white shirt or wall doesn't, however the shot was exposed or is printed.
    The glow's strength is the clipped light as this shot is printed (its balance), so it is applied after the blur."""
    codes = np.linspace(0, 1, 65536)
    light = color.decode(np.repeat(codes[:, None], 3, axis=1), sc["assumed"])[:, 0]  # one channel's transfer
    stops = np.log2(np.maximum(light, 1e-12) / np.interp(color.CLIP, codes, light))  # below clip, per code value
    near = np.clip(1 + stops / look.halation_from, 0, 1)
    clipped = color.luminance(color.to_linear_709(np.full(3, color.CLIP), sc["assumed"]) * balance(sc, look))
    return (near * near * (3 - 2 * near)).astype(np.float32), (look.halation * clipped * np.array(look.halation_tint)).astype(np.float32)


def vignette(size: tuple[int, int], look: Look, squeeze: float = 1.0) -> np.ndarray:
    """A mask that darkens the edges: untouched out to VIGNETTE_FLAT of the way to the corners, then rolling off
    smoothly to look.vignette stops darker in the corners. A natural cos^4 lens falloff starts in the middle and reads
    as a darker picture rather than darker edges; a flat centre keeps the subject as graded and frames it.

    A lens darkens in a circle on the sensor, so through an anamorphic lens the falloff desqueezes to an oval as wide
    as the squeeze: the top and bottom edges darken too, not only the sides of a wide frame."""
    w, h = size
    y, x = np.ogrid[:h, :w]
    d = np.hypot((x - w / 2) / squeeze, y - h / 2) / np.hypot(w / 2 / squeeze, h / 2)
    t = np.clip((d - VIGNETTE_FLAT) / (1 - VIGNETTE_FLAT), 0, 1)
    return (2.0 ** (-look.vignette * t * t * (3 - 2 * t))).astype(np.float32)


if __name__ == "__main__":
    for lk in looks():
        print(f"{lk.name:24} {lk.about}")
