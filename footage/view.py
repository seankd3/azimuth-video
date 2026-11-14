"""What picture each analysis sees: a clip's recorded frame desqueezed, the window of it a shot shows, and sizes.

Every decode in the toolkit takes its crop and scale from here, so a clip's geometry has one definition. A clip whose
squeeze isn't known yet is read as unsqueezed. Every decode reads the file `source` names: the clip itself, or for a
RAW clip its developed picture (develop.py).

A shot's framing is what a person chose: {"turn": quarter turns clockwise, "center": [x, y], "zoom": z}, each key
optional. The window is the largest rectangle of the edit's aspect that fits in the turned, desqueezed frame, made
1/zoom as large and centred on `center` (fractions of that frame). With no framing a shot is not turned, is centred and
shows its whole height or width: the 2.39:1 window, as shot. `frame` is the one door to a valid framing: the app stores
what it returns, and the render reads every framing through it, so a hand-written edit renders as the app shows it.
"""
import math
from pathlib import Path
from typing import NamedTuple

from . import develop

ASPECT = 2.39  # an edit's aspect unless it sets one: a number, or "full" for its first shot's whole frame
ZOOM = (1.0, 8.0)  # a shot is pushed in at most 8x
PLACES = 6  # decimals a framing keeps: a millionth of the frame, far under a pixel
# Where a point of the turned frame (x, y) was before the turn, in a frame w x h: one clockwise quarter turn per row.
UNTURN = (lambda x, y, w, h: (x, y), lambda x, y, w, h: (y, h - x),
          lambda x, y, w, h: (w - x, h - y), lambda x, y, w, h: (w - y, x))


class Window(NamedTuple):
    """The recorded pixels a shot shows, before its turn, and the turn."""
    x: int
    y: int
    w: int
    h: int
    turn: int
VERSION = 1  # bump when what a picture is changes, so everything measured from pictures is redone


def identity(sc: dict) -> dict:
    """Everything a clip's picture geometry depends on: part of the identity of every section read from pictures."""
    f = sc["facts"]
    developed = {"developed": develop.identity(sc)} if develop.raw(sc) else {}
    return {"view": VERSION, "squeeze": sc["assumed"]["squeeze"], "width": f["width"], "height": f["height"], **developed}


def source(clip: Path, sc: dict) -> str:
    """The file a clip's pictures are decoded from."""
    if not develop.raw(sc):
        return str(clip)
    picture = develop.path(clip, sc)
    if not picture.exists():
        raise ValueError(f"{clip.name} is not developed yet: run python -m footage")
    return str(picture)


def squeeze(sc: dict) -> float:
    return sc["assumed"]["squeeze"] or 1.0


def full_width(sc: dict) -> float:
    """Width of the whole desqueezed frame, in units of its height."""
    f = sc["facts"]
    return f["width"] * squeeze(sc) / f["height"]


def aspect(value, scs: list) -> float:
    """An edit's aspect as a number: its setting, or for "full" the first shot's whole frame."""
    return full_width(scs[0]) if value == "full" else float(value)


def turned(sc: dict, turn: int) -> tuple[float, float]:
    """The desqueezed frame after `turn` clockwise quarter turns, in recorded rows."""
    w, h = full_width(sc) * sc["facts"]["height"], sc["facts"]["height"]
    return (h, w) if turn % 2 else (w, h)


def fitted(sc: dict, turn: int, aspect: float, zoom: float) -> tuple[float, float]:
    """The window's size in the turned frame: the largest of `aspect` that fits, made 1/zoom as large."""
    fw, fh = turned(sc, turn)
    w, h = (fh * aspect, fh) if fw / fh >= aspect else (fw, fw / aspect)
    return w / zoom, h / zoom


def frame(sc: dict, framing: dict | None, aspect: float) -> dict:
    """A shot's framing made valid for an edit of `aspect`: a quarter turn, a zoom in ZOOM, and the window inside the
    frame. Idempotent, also through an edit file: the values are kept to PLACES decimals (the centre's limits rounded
    inward), which JSON carries exactly, so a framing read back from a file is still what this returns."""
    f = framing or {}
    turn, zoom = int(f.get("turn", 0)) % 4, round(min(max(float(f.get("zoom", 1)), ZOOM[0]), ZOOM[1]), PLACES)
    (fw, fh), (w, h) = turned(sc, turn), fitted(sc, turn, aspect, zoom)
    k = 10 ** PLACES

    def inside(c: float, half: float) -> float:
        return min(max(round(float(c), PLACES), math.ceil(half * k) / k), math.floor((1 - half) * k) / k)
    cx, cy = f.get("center", (0.5, 0.5))
    return {"turn": turn, "center": [inside(cx, w / 2 / fw), inside(cy, h / 2 / fh)], "zoom": zoom}


def window(sc: dict, framing: dict | None = None, aspect: float = ASPECT) -> Window:
    """The recorded pixels a shot shows: even sizes (chroma is subsampled), centred where its framing says."""
    f = frame(sc, framing, aspect)
    turn, s, (W, H) = f["turn"], squeeze(sc), (sc["facts"]["width"], sc["facts"]["height"])
    (fw, fh), (w, h) = turned(sc, turn), fitted(sc, turn, aspect, f["zoom"])
    rw, rh = (h, w) if turn % 2 else (w, h)  # across and down the recorded frame, in rows
    rw, rh = round(rw / s / 2) * 2, round(rh / 2) * 2
    x, y = UNTURN[turn](f["center"][0] * fw, f["center"][1] * fh, W * s, H)
    return Window(min(max(round(x / s - rw / 2), 0), W - rw), min(max(round(y - rh / 2), 0), H - rh), rw, rh, turn)


def master(scs: list, aspect: float = ASPECT) -> tuple[int, int]:
    """The master's size: `aspect`, as tall as the shortest window any clip shows unframed, so the footage sets it and
    no clip is upscaled vertically unless its framing pushes in or turns it."""
    h = min(window(sc, None, aspect).h for sc in scs)
    return round(h * aspect / 2) * 2, h


def size(sc: dict, width: int) -> tuple[int, int]:
    """The whole desqueezed frame `width` pixels wide."""
    return width, round(width / full_width(sc) / 2) * 2


def cpu(sc: dict, width: int) -> str:
    """ffmpeg filter text reading the whole desqueezed frame `width` pixels wide."""
    return "scale={}:{}".format(*size(sc, width))


def grey(clip: Path, sc: dict, width: int, start: float = 0, frames: int | None = None) -> list[str]:
    """An ffmpeg command writing the whole desqueezed frames `width` pixels wide as 8-bit grey, from `start` on.
    NVDEC decodes and scales them on the GPU; it can't open a developed RAW picture (8K 4:4:4), so the CPU decodes that."""
    gpu = not develop.raw(sc)
    scale = "scale_cuda={}:{}:format=nv12,hwdownload,format=nv12".format(*size(sc, width)) if gpu else cpu(sc, width)
    return ["ffmpeg-gpu", "-v", "error", *(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"] if gpu else []),
            "-ss", f"{start:.3f}", "-i", source(clip, sc), *(["-frames:v", str(frames)] if frames else []),
            "-vf", f"{scale},format=gray", "-f", "rawvideo", "-"]
