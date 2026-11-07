"""A RAW clip's picture: each frame developed by LibRaw into the code values the camera records for its assumed log
curve and gamut, so every reader sees a RAW clip the way it sees the camera's own clips.

LibRaw reads Canon Cinema RAW Light (.CRM): each frame is one of the file's raw images. A frame is demosaiced (AHD),
white-balanced as shot, clipped to white where the sensor saturated, taken to the assumed gamut with LibRaw's camera
matrix, and encoded with the assumed log curve; the sensor's saturation is the top code value. The result is stored
as all-intra 12-bit 4:4:4 HEVC, full range, with the clip's sound, in the day's `.developed/` folder.

The file is named by its development's identity (code version, decoder version, demosaic, white balance, log curve and
gamut). That identity is part of view.identity, so changing any of them puts every section read from pictures out of
date at once, and the next run develops the clip again.
"""
import ctypes
import hashlib
import json
import os
import re
import subprocess
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from functools import cache
from fractions import Fraction
from pathlib import Path

import numpy as np

from . import color, library, probe, sidecar

RAW = {".crm"}
VERSION = 1  # bump when development changes what a frame's code values are
DEMOSAIC = 3  # LibRaw's AHD
QUALITY = 4  # x265 CRF: near-lossless at 12 bits
DECODERS = 3  # frames developed at once; each LibRaw decode also uses several threads
FOLDER = ".developed"
# LibRaw built from source with its 2 GB cap on CR3 and CRM files raised (LIBRAW_MAX_CR3_RAW_FILE_SIZE): a minute of 8K
# RAW is about 11 GB, and the packaged build refuses any file over 2 GB as "too big for processing".
LIBRAW = Path.home() / ".local/share/footage/vendor/libraw"
TOOLS = {**os.environ, "LD_LIBRARY_PATH": str(LIBRAW / "lib")}


def raw(sc: dict) -> bool:
    return Path(sc["facts"]["original_name"]).suffix.lower() in RAW


@cache
def libraw() -> str:
    lib = ctypes.CDLL(str(LIBRAW / "lib/libraw.so"))
    lib.libraw_version.restype = ctypes.c_char_p
    return lib.libraw_version().decode()


def identity(sc: dict) -> dict:
    a = sc["assumed"]
    return {"develop": VERSION, "decoder": f"LibRaw {libraw()}", "demosaic": "AHD", "white": "as shot",
            "highlights": "clip", "log": a["log"], "gamut": a["gamut"]}


def path(clip: Path, sc: dict) -> Path:
    """The developed picture of these bytes by this development: a file left by another take of the same name never matches."""
    made_from = {**identity(sc), "sha256": sc["facts"]["sha256"]}
    tag = hashlib.sha1(json.dumps(made_from, sort_keys=True).encode()).hexdigest()[:12]
    return clip.parent / FOLDER / f"{clip.name}.{tag}.mov"


def layout(clip: Path) -> tuple[int, tuple[int, int], np.ndarray]:
    """How many frames LibRaw finds in the file, the size it develops them at, and its camera-to-Rec.709 matrix for
    white-balanced camera RGB."""
    out = subprocess.run([str(LIBRAW / "bin/raw-identify"), "-v", str(clip)], capture_output=True, text=True, check=True,
                         env=TOOLS).stdout
    frames = int(re.search(r"Number of raw images: (\d+)", out).group(1))
    size = tuple(int(v) for v in re.search(r"Output size: +(\d+) x (\d+)", out).groups())
    rows = re.search(r"Camera2RGB matrix[^\n]*\n" + r"([-\d.\s]+)\n" * 3, out).groups()
    return frames, size, np.array([[float(v) for v in r.split()] for r in rows])


def frame(clip: Path, n: int) -> bytes:
    """Frame n as a 16-bit linear PPM in white-balanced camera RGB, where 65535 is the sensor's saturation."""
    return subprocess.run([str(LIBRAW / "bin/dcraw_emu"), "-s", str(n), "-4", "-w", "-o", "0", "-H", "0", "-q", str(DEMOSAIC), "-Z", "-",
                           str(clip)], capture_output=True, check=True, env={**TOOLS, "OMP_NUM_THREADS": "8"}).stdout


def develop(clip: Path, sc: dict) -> Path:
    out = path(clip, sc)
    out.parent.mkdir(exist_ok=True)
    frames, (lw, lh), rgb_cam = layout(clip)
    f, a = sc["facts"], sc["assumed"]
    m = color.from_709(a) @ rgb_cam  # white-balanced camera RGB to the assumed gamut
    with open(out.with_name(out.name + ".encode.cube"), "w") as lut:
        x = np.linspace(0, 1, 65536)
        top = color.decode(np.ones(1), a)[0]  # saturation becomes the top code value
        lut.write("LUT_1D_SIZE 65536\n")
        np.savetxt(lut, np.repeat(color.encode(x * top, a)[:, None], 3, axis=1), fmt="%.7f")
    mixer = ":".join(f"{k}={m[i, j]:.6f}" for i, row in enumerate("rgb") for j, k in enumerate(row + c for c in "rgb"))
    w, h = f["width"], f["height"]
    tmp = out.with_name(out.name + ".part.mov")
    cmd = ["ffmpeg-gpu", "-v", "error", "-y", "-f", "ppm_pipe", "-framerate", f["fps"], "-i", "-", "-i", str(clip),
           "-map", "0:v", "-map", "1:a?", "-filter:v",
           # LibRaw's frame can be a pixel short of the recorded size: the edge is repeated to fill it.
           f"format=gbrp16le,pad={w}:{h}:0:0,fillborders=right={w - lw}:bottom={h - lh}:mode=smear,colorchannelmixer={mixer},"
           f"lut1d=file='{lut.name}',zscale=m=709:r=full,format=yuv444p12le",  # swscale's 12-bit full range is 0.3% off
           "-c:v", "libx265", "-preset", "ultrafast", "-crf", str(QUALITY),
           "-x265-params", "keyint=1:range=full:colorprim=bt709:transfer=bt709:colormatrix=bt709:log-level=error",
           "-color_range", "pc", "-colorspace", "bt709", "-tag:v", "hvc1", "-c:a", "copy", "-frames:v", str(frames), str(tmp)]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        with ThreadPoolExecutor(DECODERS) as pool:
            ahead = deque()  # frames decode out of order but are written in order, at most 2 * DECODERS held
            for n in range(frames):
                ahead.append(pool.submit(frame, clip, n))
                if len(ahead) >= 2 * DECODERS:
                    enc.stdin.write(ahead.popleft().result())
            while ahead:
                enc.stdin.write(ahead.popleft().result())
        enc.stdin.close()
        if enc.wait():
            raise RuntimeError(f"encoding {clip.name} failed")
        os.rename(tmp, out)
    finally:
        enc.kill()
        tmp.unlink(missing_ok=True)
        Path(lut.name).unlink(missing_ok=True)
    for old in out.parent.glob(f"{clip.name}.*.mov"):  # an earlier development nothing reads any more
        if old != out:
            old.unlink()
    return out


def build(lib: Path, report: list) -> None:
    """Develop each RAW clip whose picture for its current identity doesn't exist yet."""
    for clip in library.clips(lib):
        try:
            sc = sidecar.read(clip)
            if sc is not None and raw(sc) and probe.unchanged(clip, sc["facts"]) and not path(clip, sc).exists():
                develop(clip, sc)
                report.append(("developed", clip.name, clip.parent.name))
        except Exception as e:  # the clip stays undeveloped and the next run retries it
            report.append(("could not develop", f"{clip.parent.name}/{clip.name}", repr(e)[:200]))
