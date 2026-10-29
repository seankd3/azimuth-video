"""What picture each analysis sees: a clip's recorded frame desqueezed, the 2.39:1 window the edit shows, and sizes.

Every decode in the toolkit takes its crop and scale from here, so a clip's geometry has one definition. A clip whose
squeeze isn't known yet is read as unsqueezed.
"""
ASPECT = 2.39
VERSION = 1  # bump when what a picture is changes, so everything measured from pictures is redone


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


def cuda(sc: dict, width: int) -> str:
    """The same for frames decoded on the GPU (NVDEC): scaled there, then brought back as 8-bit 4:2:0."""
    return "scale_cuda={}:{}:format=nv12,hwdownload,format=nv12".format(*size(sc, width))
