"""Stabilizing a shot: keep the camera's deliberate move, take out the shake.

The camera's motion is what most of the frame agrees on. Every frame of the shot is read small and desqueezed
(NVDEC) and cut into a grid of cells; corners are found in every cell and followed to the next frame (KLT, checked
by following them back), and a similarity (shift and roll) is fitted to them with RANSAC. A frame counts only when
the points that agree are spread over most cells: a hand or a person moving in front of a locked-off camera moves a
few cells, not the frame, so it is never taken for shake.
A shot where many frames don't agree (parallax from a move past near objects) is left alone: one 2D correction
can't fix it, and a wrong one makes the picture swim.

The deliberate move is the camera's path smoothed over SMOOTH seconds; the shake is what is left. A shot whose shake
is under SHAKE_MIN pixels of the master is left alone. The correction moves the 2.39:1 window inside the full
desqueezed frame, which is wider than the window, so correcting side to side costs nothing; correcting up and down,
and roll, zooms in just enough to keep the edges filled, at most MOST_ZOOM. If the shake needs more, the smoothing is
relaxed until it fits.
"""
import subprocess
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d

VERSION = 1
W = 1280
GX, GY = 8, 4
AGREE = 0.5  # share of cells with corners whose corners must move together for a frame's motion to count
PER_CELL = 12  # corners followed in each cell
TRUST = 0.9  # share of frames that must count for the shot's path to be trusted
SMOOTH = 0.6  # seconds: the deliberate move is the path smoothed this much
SHAKE_MIN = 1.5  # RMS shake, in pixels of the master, below which a shot is left alone
MOST_ZOOM = 1.06


def full_width(sc: dict) -> float:
    """Width of the whole desqueezed frame, in units of its height."""
    f = sc["facts"]
    return f["width"] * sc["assumed"]["squeeze"] / f["height"]


def motion(clip: Path, sc: dict, start: float, frames: int) -> np.ndarray:
    """Frame-to-frame camera motion: x, y (in widths of the desqueezed frame) and roll (rad); NaN where cells disagree."""
    import cv2
    h = round(W / full_width(sc) / 2) * 2
    p = subprocess.Popen(["ffmpeg-gpu", "-v", "error", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
                          "-ss", f"{start:.3f}", "-i", str(clip), "-frames:v", str(frames),
                          "-vf", f"scale_cuda={W}:{h}:format=nv12,hwdownload,format=nv12,format=gray", "-f", "rawvideo", "-"],
                         stdout=subprocess.PIPE)
    ch, cw = h // GY, W // GX
    centre = np.array([W / 2, h / 2], np.float32)
    moves, last = [], None
    while len(b := p.stdout.read(W * h)) == W * h:
        y = np.frombuffer(b, np.uint8).reshape(h, W)
        if last is not None:
            move = (np.nan,) * 3
            found = [f + np.float32([i * cw, j * ch]) for j in range(GY) for i in range(GX)
                     if (f := cv2.goodFeaturesToTrack(last[j * ch:(j + 1) * ch, i * cw:(i + 1) * cw], PER_CELL, 0.01, 8)) is not None]
            pts = np.concatenate(found) if found else None
            if pts is not None and len(pts) >= 8:
                nxt, ok, _ = cv2.calcOpticalFlowPyrLK(last, y, pts, None, winSize=(21, 21), maxLevel=3)
                back, ok2, _ = cv2.calcOpticalFlowPyrLK(y, last, nxt, None, winSize=(21, 21), maxLevel=3)
                good = (ok.ravel() == 1) & (ok2.ravel() == 1) & (np.linalg.norm(back - pts, axis=2).ravel() < 0.3)
                a0, a1 = pts[good].reshape(-1, 2) - centre, nxt[good].reshape(-1, 2) - centre
                if len(a0) >= 8:
                    m, inl = cv2.estimateAffinePartial2D(a0, a1, method=cv2.RANSAC, ransacReprojThreshold=0.5)
                    cell = (a0[:, 1] + h / 2) // ch * GX + (a0[:, 0] + W / 2) // cw
                    # The motion counts only when the points that agree with it are spread over most of the frame.
                    if m is not None and len(np.unique(cell[inl.ravel() == 1])) >= AGREE * len(np.unique(cell)):
                        move = (m[0, 2] / W, m[1, 2] / W, float(np.arctan2(m[1, 0], m[0, 0])))
            moves.append(move)
        last = y
    p.wait()
    return np.array(moves).reshape(-1, 3)

def shake(clip: Path, sc: dict) -> dict:
    """The clip's shake second by second, in pixels of a 2160-line master: what the camera moved beyond its smoothed path.

    A second where most frames didn't move as one (a crowd, a move past near objects) is None: it can't be told."""
    from fractions import Fraction
    fps = float(Fraction(sc["facts"]["fps"]))
    m = motion(clip, sc, 0, round(sc["facts"]["duration"] * fps))
    path = np.vstack([np.zeros(3), np.cumsum(np.nan_to_num(m), axis=0)])[:, :2] * 2160 * full_width(sc)
    left = np.hypot(*(path - gaussian_filter1d(path, SMOOTH * fps, axis=0, mode="nearest")).T)
    unknown = np.append(False, np.isnan(m).any(axis=1))
    seconds = [slice(round(s * fps), round((s + 1) * fps)) for s in range(int(np.ceil(len(path) / fps)))]
    return {"v": VERSION, "by_second": [None if unknown[s].mean() > 1 - TRUST else round(float(np.sqrt((left[s] ** 2).mean())), 1)
                                        for s in seconds if len(left[s])]}


def plan(moves: np.ndarray, fps: float, sc: dict, size: tuple[int, int]) -> dict | None:
    """Per-frame correction for a shot at the master's size, or None to leave it alone.

    The correction is how far to move the picture (x, y in master pixels) and turn it (rad) on each frame, and the
    zoom that keeps the edges filled."""
    if len(moves) < 2 or np.isnan(moves).any(axis=1).mean() > 1 - TRUST:
        return None
    w, h = size
    fw = h * full_width(sc)
    path = np.vstack([np.zeros(3), np.cumsum(np.nan_to_num(moves), axis=0)]) * [fw, fw, 1]
    for smooth in (SMOOTH, SMOOTH / 2, SMOOTH / 4, SMOOTH / 8):
        fix = gaussian_filter1d(path, smooth * fps, axis=0, mode="nearest") - path
        if smooth == SMOOTH and np.sqrt((fix[:, :2] ** 2).sum(1).mean()) < SHAKE_MIN:
            return None
        roll = np.abs(fix[:, 2]).max()
        # The zoom that keeps a turned, shifted w x h window inside the frame, side to side and up and down.
        zoom = max(1.0, ((w / 2 + h / 2 * roll + np.abs(fix[:, 0]).max()) / (fw / 2)),
                   ((h / 2 + w / 2 * roll + np.abs(fix[:, 1]).max()) / (h / 2)))
        if zoom <= MOST_ZOOM:
            break
    zoom = min(zoom, MOST_ZOOM)
    return {"zoom": float(zoom), "fix": fix, "roll": bool(roll * w / 2 > 0.5), "smooth": smooth}

