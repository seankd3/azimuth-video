"""The smoothest retime for a focus pull in a still shot: try several, measure each, keep the best.

A retime maps source time to output time so the focus travels on an eased curve over the pull's own duration; frames
are blended at four times the frame rate and averaged back down, a "focus blur" that irons out what's left. How far
the focus has travelled at each frame can be read two ways (projected between the pull's start and end states, or
added up frame to frame); which reads a given pull better varies, so each candidate is rendered small and its
frame-to-frame focus speed measured. The smoothest is kept, if it beats the untouched pull.
"""
import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d, median_filter

from . import focus, view

BLUR = 4  # frames blended per output frame, at BLUR times the frame rate
MOST_KNOTS = 48  # an ffmpeg expression this deep still parses
KEEP_IF_BETTER = 0.9  # a retime must cut jitter by at least 10% to replace the original


def ease(x):
    return x * x * (3 - 2 * x)


def monotone(y: np.ndarray) -> np.ndarray:
    """The closest never-decreasing sequence (pool adjacent violators)."""
    blocks = []
    for v in y:
        blocks.append([float(v), 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            (a, n), (b, m) = blocks[-2], blocks[-1]
            blocks[-2:] = [[(a * n + b * m) / (n + m), n + m]]
    return np.concatenate([[v] * n for v, n in blocks])


def speed(sharp: np.ndarray) -> np.ndarray:
    return np.abs(np.diff(median_filter(sharp, size=(3, 1)), axis=0)).mean(1)


def projected(sharp: np.ndarray, a: int, b: int) -> np.ndarray:
    s = median_filter(sharp, size=(3, 1))
    d = s[b] - s[a]
    return monotone(((s[a:b + 1] - s[a]) @ d) / max(float(d @ d), 1e-9))


def added_up(sharp: np.ndarray, a: int, b: int) -> np.ndarray:
    sp = speed(sharp)
    still = np.concatenate([sp[:max(a - 2, 1)], sp[b + 2:]])
    floor = np.median(still) if len(still) else 0.0  # what a still picture measures, frame to frame
    return np.concatenate([[0], np.cumsum(gaussian_filter1d(np.clip(sp[a:b] - floor, 0, None), 1.5))])


def knots(t: np.ndarray, travel: np.ndarray) -> list[list[float]]:
    """(source time, output time) pairs over the pull: output time is when that much travel happens on the eased curve."""
    step = max(1, int(np.ceil(len(t) / MOST_KNOTS)))
    keep = sorted(set(range(0, len(t), step)) | {len(t) - 1})
    t, travel = t[keep], np.maximum.accumulate(travel[keep])
    travel = (travel - travel[0]) / max(travel[-1] - travel[0], 1e-9)
    mix = 0.9 * travel + 0.1 * (t - t[0]) / (t[-1] - t[0])  # a pause in the pull still takes some time
    grid = np.linspace(0, 1, 4001)
    u = t[0] + (t[-1] - t[0]) * np.interp(mix, ease(grid), grid)
    return [[round(float(x), 5), round(float(y), 5)] for x, y in zip(t, u)]


def filters(points: list, start: float, dur: float, rate: str) -> str:
    """ffmpeg filters that retime a shot [start, start + dur] through the given knots (in clip seconds)."""
    k = [(0.0, 0.0)]
    for t, u in points:
        if start < t < start + dur and t - start > k[-1][0]:
            k.append((t - start, u - start))
    if k[-1][0] < dur:
        k.append((dur, dur))
    expr = None
    for (t0, u0), (t1, u1) in reversed(list(zip(k, k[1:]))):
        seg = f"{u0:.5f}+(T-{t0:.5f})*{(u1 - u0) / (t1 - t0):.6f}"
        expr = seg if expr is None else f"if(lt(T,{t1:.5f}),{seg},{expr})"
    return (f"setpts='({expr})/TB',framerate=fps={rate}*{BLUR}:interp_start=0:interp_end=255:scene=100,"
            f"tmix=frames={BLUR},framestep={BLUR},setpts=N/({rate})/TB,")


def jitter(clip: Path, sc: dict, start: float, n: int, sa: int, sb: int, chain: str) -> float:
    """Frame-to-frame unevenness of the focus speed through the pull, measured on a small render read as focus reads."""
    W, H = view.size(sc, focus.W)
    g = (f"[0:v]trim=end_frame={n},setpts=PTS-STARTPTS,{view.cpu(sc, focus.W)},{chain}"
         f"tpad=stop_mode=clone:stop={BLUR},trim=end_frame={n},format=gray")
    raw = subprocess.run(["ffmpeg-gpu", "-v", "error", "-ss", f"{start:.3f}", "-i", str(clip), "-filter_complex", g,
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    y = np.frombuffer(raw, np.uint8).reshape(-1, H, W).astype(np.float32)
    lap = 4 * y[:, 1:-1, 1:-1] - y[:, :-2, 1:-1] - y[:, 2:, 1:-1] - y[:, 1:-1, :-2] - y[:, 1:-1, 2:]
    th, tw = (H - 2) // 4, (W - 2) // 8
    v = speed(np.log(lap[:, :th * 4, :tw * 8].reshape(len(y), 4, th, 8, tw).var(axis=(2, 4)) + 1).reshape(len(y), -1))[sa:sb]
    trend = gaussian_filter1d(v, 6)
    return float(np.sqrt(np.mean((v - trend) ** 2)) / max(trend.mean(), 1e-9))


def best(clip: Path, sc: dict, sharp: np.ndarray, a: int, b: int) -> dict | None:
    """The smoothest retime for the pull at frames a..b of this clip, or None if nothing beats leaving it alone."""
    rate, duration = sc["facts"]["fps"], sc["facts"]["duration"]
    fps = float(Fraction(rate))
    start = max(a / fps - 0.6, 0.0)
    n = round((min(b / fps + 0.8, duration - 0.05) - start) * fps)
    sa, sb = round(a - start * fps), round(b - start * fps)
    t = np.arange(a, b + 1) / fps
    before = jitter(clip, sc, start, n, sa, sb, "")
    tried = []
    for travel in (projected(sharp, a, b), added_up(sharp, a, b)):
        k = knots(t, travel)
        tried.append((jitter(clip, sc, start, n, sa, sb, filters(k, start, n / fps, rate)), k))
    after, k = min(tried, key=lambda x: x[0])
    if after > before * KEEP_IF_BETTER:
        return None
    return {"knots": k, "jitter": [round(before, 3), round(after, 3)]}
