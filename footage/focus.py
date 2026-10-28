"""Focus pulls in a clip: when the focus starts moving and when it settles, which way it went, and how far.

A pull is sharpness moving across a still picture. Every frame is read small and desqueezed (NVDEC); sharpness is
tracked in an 8x4 grid of regions and motion in a coarse thumbnail. A pull is a stretch where the regions' sharpness
changes a lot, one way (not the back-and-forth of hands crossing a shallow focus plane), while the picture holds still.
Its start and end are where 5% and 95% of the focus change has happened: cut just before one and just after the other.
Each pull also records how still the picture was (motion, and pan from frame-to-frame phase correlation). A pull in a
still shot gets `smooth`: the retime that makes it smoothest (smooth.py), which the render applies.
"""
import subprocess
from pathlib import Path

import numpy as np
from scipy.ndimage import median_filter, uniform_filter1d

VERSION = 4
W, H, GX, GY = 640, 210, 8, 4
NET_MIN = 0.45  # mean change in log sharpness per second across regions
COHERENT = 0.6  # net change over a second / the path it took: one way, not back and forth
STILL = 1.2  # thumbnail change per frame, above which the camera or subject is moving
PULL_MIN = 1.2  # mean log-sharpness change from start to end for a pull worth cutting on
PULL_SECONDS = 1.0
PULL_STILL = 1.0
STILL_MOTION, STILL_PAN = 0.35, 0.08  # only a pull with nothing else moving is retimed: no subject motion, no pan


def grid_sharpness(clip: Path, fps: float, squeeze: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Log sharpness per region per frame, a coarse thumbnail per frame for motion, and the pan (pixels per frame)."""
    import cv2
    h = round(W / (squeeze * 4096 / 2160) / 2) * 2 if squeeze else H
    p = subprocess.Popen(["ffmpeg-gpu", "-v", "error", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-i", str(clip),
                          "-vf", f"scale_cuda={W}:{h}:format=nv12,hwdownload,format=nv12,format=gray", "-f", "rawvideo", "-"],
                         stdout=subprocess.PIPE)
    sharp, thumbs, pans, last = [], [], [], None
    window = cv2.createHanningWindow((W, h), cv2.CV_32F)
    while len(b := p.stdout.read(W * h)) == W * h:
        y = np.frombuffer(b, np.uint8).reshape(h, W).astype(np.float32)
        pans.append(0.0 if last is None else float(np.hypot(*cv2.phaseCorrelate(last, y, window)[0])))
        last = y
        lap = 4 * y[1:-1, 1:-1] - y[:-2, 1:-1] - y[2:, 1:-1] - y[1:-1, :-2] - y[1:-1, 2:]
        th, tw = (h - 2) // GY, (W - 2) // GX
        sharp.append(np.log(lap[:th * GY, :tw * GX].reshape(GY, th, GX, tw).var(axis=(1, 3)) + 1).ravel())
        thumbs.append(y[:h // 10 * 10].reshape(h // 10, 10, W // 10, 10).mean(axis=(1, 3)))
    p.wait()
    return np.array(sharp), np.array(thumbs), np.array(pans)


def where(regions: np.ndarray) -> str | None:
    if not regions.any():
        return None
    row, col = np.divmod(np.nonzero(regions)[0], GX)
    return f'{["top", "middle", "bottom"][min(int(row.mean() / GY * 3), 2)]} {["left", "centre", "right"][min(int(col.mean() / GX * 3), 2)]}'


def pulls(sharp: np.ndarray, thumbs: np.ndarray, pans: np.ndarray, fps: float) -> list[dict]:
    n = len(sharp)
    half = int(0.5 * fps)
    if n < 2 * half + 2:
        return []
    s = uniform_filter1d(median_filter(sharp, size=(7, 1)), 9, axis=0)
    steps = np.abs(np.diff(s, axis=0)).mean(1)
    net, path = np.zeros(n), np.ones(n)
    net[half:n - half] = np.abs(s[2 * half:] - s[:n - 2 * half]).mean(1)
    path[half:n - half] = np.convolve(steps, np.ones(2 * half), "valid")[:n - 2 * half]
    motion = np.zeros(n)
    motion[1:] = np.abs(np.diff(thumbs, axis=0)).mean((1, 2))
    motion = uniform_filter1d(motion, 15)
    moving = (net * fps / (2 * half) > NET_MIN) & (net / np.maximum(path, 1e-6) > COHERENT) & (motion < STILL)
    # Each run of focus movement, widened to where the focus moves at all, trimmed to 5%..95% of its change.
    spans, t = [], 0
    while t < n:
        if moving[t]:
            a = t
            while t < n and moving[t:t + int(0.3 * fps)].any():
                t += 1
            a0, b0 = max(a - half, 0), min(t + half, n - 1)
            cum = np.concatenate([[0], np.cumsum(steps[a0:b0])])
            if cum[-1] > 0:
                spans.append([a0 + int(np.searchsorted(cum, 0.05 * cum[-1])), a0 + int(np.searchsorted(cum, 0.95 * cum[-1]))])
        t += 1
    merged = []
    for a, b in sorted(spans):  # pieces of one pull that touch become one pull
        if merged and a <= merged[-1][1] + int(0.3 * fps):
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    # Focus that comes in and goes out again in one move is two pulls: split it at its sharpest frame.
    level = s.mean(1)
    split = []
    for a, b in merged:
        peak = a + int(np.argmax(level[a:b + 1]))
        if a < peak < b and level[peak] - max(level[a], level[b]) > 0.7:
            split += [[a, peak], [peak, b]]
        else:
            split.append([a, b])
    out = []
    for a, b in split:
        delta = s[b] - s[a]
        strength = float(np.abs(delta).mean())
        if strength < PULL_MIN or (b - a) / fps < PULL_SECONDS or motion[a:b + 1].mean() > PULL_STILL:
            continue
        gained, lost = delta > 0.5, delta < -0.5
        kind = "rack" if gained.sum() >= 3 and lost.sum() >= 3 else ("focus in" if gained.sum() > lost.sum() else "focus out")
        out.append({"start": round(a / fps, 2), "end": round(b / fps, 2), "frames": [int(a), int(b)], "kind": kind,
                    "from": where(lost), "to": where(gained), "strength": round(strength, 2),
                    "motion": round(float(motion[a:b + 1].mean()), 2), "pan": round(float(np.median(pans[a + 1:b + 1])), 3)})
    return out


def focus(clip: Path, sc: dict) -> dict:
    num, den = map(int, sc["facts"]["fps"].split("/"))
    from . import smooth
    fps = num / den
    sharp, thumbs, pans = grid_sharpness(clip, fps, sc["assumed"]["squeeze"])
    found = pulls(sharp, thumbs, pans, fps)
    for p in found:
        still = p["motion"] <= STILL_MOTION and p["pan"] <= STILL_PAN
        p["smooth"] = smooth.best(clip, sharp, *p["frames"], fps, sc["facts"]["fps"], sc["facts"]["duration"]) if still else None
    return {"v": VERSION, "pulls": found}
