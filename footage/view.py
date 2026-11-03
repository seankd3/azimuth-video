"""What picture each analysis sees: a clip's recorded frame desqueezed, the 2.39:1 window the edit shows, and sizes.

Every decode in the toolkit takes its crop and scale from here, so a clip's geometry has one definition. A clip whose
squeeze isn't known yet is read as unsqueezed. Every decode reads the file `source` names: the clip itself, or for a
RAW clip its developed picture (develop.py).
"""
from pathlib import Path

from . import develop

ASPECT = 2.39
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


def window(sc: dict) -> tuple[int, int]:
    """The centred region, in recorded pixels, that desqueezes to 2.39:1."""
    f, s = sc["facts"], squeeze(sc)
    if f["width"] * s / f["height"] >= ASPECT:
        return round(f["height"] * ASPECT / s / 2) * 2, f["height"]
    return f["width"], round(f["width"] * s / ASPECT / 2) * 2


def master(scs: list) -> tuple[int, int]:
    """The master's size: the largest 2.39:1 frame every clip can fill without upscaling vertically."""
    h = min(window(sc)[1] for sc in scs)
    return round(h * ASPECT / 2) * 2, h


def full_frame(sc: dict, size: tuple[int, int]) -> tuple[float, float]:
    """The whole recorded frame, desqueezed, at the scale where its 2.39:1 window fills size."""
    cw, ch = window(sc)
    return sc["facts"]["width"] * size[0] / cw, sc["facts"]["height"] * size[1] / ch


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
