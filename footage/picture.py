"""The picture path, on the GPU: a shot's camera frames to its graded display picture, for renders and stills alike.

ffmpeg decodes a shot and frames it in recorded pixels (trim, retime, the crop to the 2.39:1 window) and hands over its
YUV untouched. Here the GPU turns it into RGB code values, desqueezes them to the master's size (Lanczos), prints them
through the shot's grade (grade.print_lut, by tetrahedral interpolation), adds the halation as light, darkens the
corners, and returns display Rec.709; for the encoder it also makes the 10-bit 4:2:0 frame. A frame is a [3, H, W]
float tensor, 0..1. Each step is compiled (torch.compile) into a few fused kernels: run one operation at a time, a 5K
frame took 160 ms and its temporaries 7 GB of GPU memory. Memory is a few frames however long the edit runs, and the
CPU only decodes.

Halation (grade.halation): each pixel's glow source is how close its brightest channel came to clipping. The source is
taken to quarter size, blurred twice (a tight core and a wide skirt), mixed 0.6 to 0.4, tinted, brought back to full
size and added to the print in linear display light (2.4 gamma), where light adds.
"""
import os
import queue
import re
import subprocess
import threading
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np

from . import grade

LANCZOS = 3
AHEAD = 3  # frames decoded ahead, and graded frames waiting for the encoder
# Frames cross between the CPU and the GPU through a few pinned buffers allocated once and reused: a fresh 30 MB
# buffer per frame made every frame fault in new pages, which under the job's memory limit slowed a render tenfold.
RING = AHEAD + 2  # a buffer is reused only after the frames queued after it have moved on
CORE, SKIRT = 0.004, 0.014  # the two blurs' sigmas, as shares of the glow spread (a quarter of the picture height)


@cache
def device():
    import torch
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def tensor(a):
    import torch
    return torch.as_tensor(np.ascontiguousarray(a), device=device())


@cache
def compiled(fn):
    """fn compiled into fused kernels, kept between runs on disk (never in /tmp). It compiles in this process: a pool
    of compiler processes, each with torch loaded, took gigabytes for kernels compiled once per machine."""
    os.environ.setdefault("TORCHINDUCTOR_CACHE_DIR", str(Path.home() / ".cache/footage/torch"))
    os.environ.setdefault("TORCHINDUCTOR_COMPILE_THREADS", "1")
    import torch
    return torch.compile(fn, dynamic=False)


def ring(n: int, dtype):
    """Endlessly, RING pinned host buffers of n elements in turn."""
    import itertools
    import torch
    return itertools.cycle([torch.empty(n, dtype=dtype, pin_memory=device().type == "cuda") for _ in range(RING)])


@cache
def resampler(n_in: int, n_out: int, cosited: bool = False) -> tuple | None:
    """Lanczos-3 resampling from n_in to n_out samples: for each output sample, the input samples it reads and their
    weights, normalized, or None when the sizes match. Shrinking widens the kernel, so nothing aliases. Samples are
    centred in the span they cover, or, cosited, on its first output sample (video chroma sits on every other luma
    sample across)."""
    if n_in == n_out and not cosited:
        return None
    scale = n_in / n_out
    support = LANCZOS * max(scale, 1.0)
    centre = np.arange(n_out) * scale if cosited else (np.arange(n_out) + 0.5) * scale - 0.5
    taps = int(np.ceil(2 * support)) + 1
    idx = np.floor(centre - support + 1).astype(int)[:, None] + np.arange(taps)
    x = (idx - centre[:, None]) / max(scale, 1.0)
    w = np.sinc(x) * np.sinc(x / LANCZOS) * (np.abs(x) < LANCZOS)
    w /= w.sum(axis=1, keepdims=True)
    return tensor(np.clip(idx, 0, n_in - 1).T.copy()), tensor(w.T.astype(np.float32).copy())


def resize(frame, across: tuple | None, down: tuple | None):
    """A [C, h, w] frame resampled across and down by resamplers (None leaves that axis)."""
    if across is not None:
        idx, wt = across
        frame = sum(frame[:, :, idx[k]] * wt[k] for k in range(idx.shape[0]))
    if down is not None:
        idx, wt = down
        frame = sum(frame[:, idx[k], :] * wt[k][:, None] for k in range(idx.shape[0]))
    return frame


def tetrahedral(lut, rgb):
    """rgb [3, H, W] in 0..1 looked up in a cube LUT [N^3, 3] (red fastest), by tetrahedral interpolation: from the
    cell's first corner along the channel with the largest fraction, then the next, to the far corner."""
    import torch
    n = round(lut.shape[0] ** (1 / 3))
    p = rgb.clamp(0, 1) * (n - 1)
    i = p.floor().clamp(max=n - 2)
    r, g, b = p - i
    base = (i[0] + n * i[1] + n * n * i[2]).long()
    first = torch.where((r >= g) & (r >= b), 0, torch.where(g >= b, 1, 2))  # the channel with the largest fraction
    hi = torch.maximum(torch.maximum(r, g), b)
    lo = torch.minimum(torch.minimum(r, g), b)
    mid = r + g + b - hi - lo
    last = torch.where((r <= g) & (r <= b) & (first != 0), 0, torch.where((g <= b) & (first != 1), 1, 2))
    stride = torch.tensor([1, n, n * n], device=rgb.device)
    s1 = stride[first]
    s2 = stride.sum() - s1 - stride[last]  # the remaining channel is the middle one
    corner = lambda c: lut[c].permute(2, 0, 1)
    return (1 - hi) * corner(base) + (hi - mid) * corner(base + s1) + (mid - lo) * corner(base + s1 + s2) + lo * corner(base + stride.sum())


def gaussian(img, sigma: float):
    """img [C, H, W] blurred by a Gaussian of sigma pixels, one axis at a time, edges repeated."""
    import torch
    import torch.nn.functional as F
    r = max(1, int(np.ceil(3 * sigma)))
    k = torch.exp(-0.5 * (torch.arange(-r, r + 1, device=img.device, dtype=img.dtype) / sigma) ** 2)
    k = (k / k.sum()).reshape(1, 1, -1)
    c = img.shape[0]
    x = F.conv1d(F.pad(img.reshape(c * img.shape[1], 1, -1), (r, r), mode="replicate"), k).reshape(img.shape)
    x = x.transpose(1, 2)
    return F.conv1d(F.pad(x.reshape(c * x.shape[1], 1, -1), (r, r), mode="replicate"), k).reshape(x.shape).transpose(1, 2)


def printed(code, across, down, lut, source, gain, mask, spread: float):
    """Recorded code values [3, h, w] to the display picture: desqueezed, printed, with halation and vignette."""
    import torch.nn.functional as F
    code = resize(code, across, down).clamp(0, 1)
    light = tetrahedral(lut, code).clamp(0, 1) ** 2.4
    h, w = code.shape[1:]
    if source is not None:
        brightest = (code.amax(0) * (source.shape[0] - 1)).round().long()
        glow = F.interpolate(source[brightest][None, None], size=(h // 4, w // 4), mode="area")[0]
        glow = 0.6 * gaussian(glow, spread * CORE) + 0.4 * gaussian(glow, spread * SKIRT)
        glow = (glow * gain[:, None, None]).clamp(max=1)
        light = (light + F.interpolate(glow[None], size=(h, w), mode="bicubic")[0].clamp(0, 1)).clamp(max=1)
    if mask is not None:
        light = light * mask
    return light.clamp(0, 1) ** (1 / 2.4)


@dataclass
class Shot:
    """One shot's grade on the GPU."""
    size: tuple[int, int]
    lut: object
    source: object | None  # the halation source per code value of the brightest channel, or None without halation
    gain: object | None
    spread: float
    mask: object | None

    def __call__(self, code):
        """Recorded code values [3, h, w] (0..1) to the display picture [3, H, W]."""
        w, h = self.size
        return compiled(printed)(code, resampler(code.shape[2], w), resampler(code.shape[1], h), self.lut, self.source,
                                 self.gain, self.mask, self.spread)


def shot(sc: dict, look: grade.Look, size: tuple[int, int]) -> Shot:
    from . import view
    source, gain = grade.halation(sc, look) if look.halation else (None, None)
    return Shot(size, tensor(grade.print_lut(sc, look)), None if source is None else tensor(source),
                None if gain is None else tensor(gain), size[1] * look.halation_spread / 4,
                tensor(grade.vignette(size, look, view.squeeze(sc))) if look.vignette else None)


def ahead(items, n: int = AHEAD):
    """The items of an iterator, produced by a thread up to n ahead of the consumer."""
    q, end = queue.Queue(n), object()

    def run():
        try:
            for x in items:
                q.put(x)
            q.put(end)
        except BaseException as e:  # handed to the consumer
            q.put(e)
    threading.Thread(target=run, daemon=True).start()
    while (x := q.get()) is not end:
        if isinstance(x, BaseException):
            raise x
        yield x


def rgb(y, cb, cr, across, down, full: bool, depth: int):
    """Planar YUV code values (0..1 of the range, chroma at its own size) to full-size RGB code values, BT.709."""
    cb, cr = resize(cb[None], across, down)[0], resize(cr[None], across, down)[0]
    top = 2 ** depth - 1
    if full:
        cb, cr = cb - 2 ** (depth - 1) / top, cr - 2 ** (depth - 1) / top
    else:
        steps = top / 2 ** (depth - 8)  # code value shares to 8-bit-equivalent steps
        y, cb, cr = (y * steps - 16) / 219, (cb * steps - 128) / 224, (cr * steps - 128) / 224
    import torch
    return torch.stack([y + 1.5748 * cr, y - 0.18733 * cb - 0.46813 * cr, y + 1.8556 * cb]).clamp(0, 1)


def frames(cmd: list[str], size: tuple[int, int], fmt: str, full: bool):
    """Each frame an ffmpeg command writes to stdout in fmt (planar YUV such as yuv422p10le, BT.709, full or limited
    range; or gbrp16le), size (w, h), as RGB code values [3, h, w] on the GPU, 0..1. Chroma is brought to full size
    with Lanczos. Frames are read and uploaded a few ahead of the caller, while ffmpeg decodes the next."""
    import torch
    w, h = size
    if fmt == "gbrp16le":
        planes, depth = [(w, h)] * 3, 16
    else:
        sub, bits = re.fullmatch(r"yuv(4\d\d)p(\d*)(?:le)?", fmt).groups()
        cw, ch = (w if sub == "444" else w // 2), (h // 2 if sub == "420" else h)
        planes, depth = [(w, h), (cw, ch), (cw, ch)], int(bits or 8)
        across, down = resampler(cw, w, cw != w), resampler(ch, h)
    n = sum(pw * ph for pw, ph in planes)

    def read():
        buffers = ring(n, torch.int16 if depth > 8 else torch.uint8)
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=0)
        try:
            while True:
                buf = next(buffers)
                view, got = memoryview(buf.numpy()).cast("B"), 0
                while got < len(view) and (k := p.stdout.readinto(view[got:])):
                    got += k
                if got < len(view):
                    break
                raw = buf.to(device())
                yield raw.int() & 0xFFFF if depth > 8 else raw.int()
        finally:
            p.stdout.close()
            if p.wait() not in (0, -13):  # -13: we stopped reading
                raise subprocess.CalledProcessError(p.returncode, cmd[0])

    for raw in ahead(read()):
        cut, out = 0, []
        for pw, ph in planes:
            out.append(raw[cut:cut + pw * ph].view(ph, pw).float() / (2 ** depth - 1))
            cut += pw * ph
        if fmt == "gbrp16le":
            yield torch.stack([out[2], out[0], out[1]])  # planes are green, blue, red
        else:
            yield compiled(rgb)(*out, across, down, full, depth)


def yuv(rgb):
    """A display frame [3, H, W] as BT.709 limited-range 10-bit 4:2:0, in P010 layout (what the GPU encoder takes),
    as int16 holding the uint16 bits."""
    import torch
    import torch.nn.functional as F
    r, g, b = rgb.clamp(0, 1)
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    uv = F.avg_pool2d(torch.stack([(b - y) / 1.8556, (r - y) / 1.5748])[None], 2)[0]  # one chroma sample per 2x2 pixels
    y10 = (64 + 876 * y).round().clamp(0, 1023)
    uv10 = (512 + 896 * uv).round().clamp(0, 1023)
    planes = torch.cat([(y10 * 64).flatten(), (uv10.permute(1, 2, 0) * 64).flatten()]).to(torch.int32)
    return (planes - 65536 * (planes > 32767)).to(torch.int16)


class Encoded:
    """Display frames as the bytes the GPU encoder takes (yuv), each in the next of RING pinned buffers: a frame's
    bytes stay valid while up to AHEAD later frames wait for the encoder."""
    buffers = None

    def __call__(self, rgb) -> np.ndarray:
        import torch
        y = compiled(yuv)(rgb)
        self.buffers = self.buffers or ring(y.numel(), torch.int16)
        buf = next(self.buffers)
        buf.copy_(y)
        return buf.numpy()
