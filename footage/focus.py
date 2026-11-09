"""Focus pulls in a clip: when the focus starts moving and when it settles, which way it went, and how far.

A pull is sharpness moving across a still picture. Every frame is read small and desqueezed (NVDEC); sharpness is
tracked in an 8x4 grid of regions and motion in a coarse thumbnail. A pull is a stretch where the regions' sharpness
changes a lot, one way (not the back-and-forth of hands crossing a shallow focus plane), while the picture holds still.
Its start and end are where 5% and 95% of the focus change has happened: cut just before one and just after the other.
Each pull also records how still the picture was (motion, and the camera's pan). A pull in a still shot gets `smooth`:
the retime that makes it smoothest (smooth.py), which the render applies.

The camera's own movement is told apart from what moves in front of it. A few hundred corners are tracked from frame to
frame (KLT). When a share of them (STILL_SHARE) hold still, the camera did: a moving machine or person leaves the
background where it was, and a camera that moves moves every corner. Otherwise the camera's movement is the one most
corners share (a RANSAC fit of shift, turn and scale). A big machine moving in front of a tripod has more corners than
the background behind it, so the fit alone took its movement for the camera's. Per
second, `camera` is how far it moved the picture (pixels per frame, W wide) and `motion` is what still changes with the
camera's movement taken out: the mean change of a thumbnail, in grey levels. A tripod reads 0.01 to 0.05 for the
camera; held by hand, a steady shot reads 0.1 to 0.5 and a shaky one 0.5 to 2. A shot the old picture-change measure
took for moving was most often only the camera shaking.
"""
import subprocess
from pathlib import Path

import numpy as np
from scipy.ndimage import median_filter, uniform_filter1d

from . import view

VERSION = 7
W, GX, GY = 640, 8, 4  # frames are read W pixels wide (smooth.py measures its retimes the same way)
NET_MIN = 0.45  # mean change in log sharpness per second across regions
COHERENT = 0.6  # net change over a second / the path it took: one way, not back and forth
STILL = 1.2  # thumbnail change per frame, above which the camera or subject is moving
PULL_MIN = 1.2  # mean log-sharpness change from start to end for a pull worth cutting on
PULL_SECONDS = 1.0
PULL_STILL = 1.0
STILL_MOTION, STILL_PAN = 0.35, 0.08  # only a pull with nothing else moving is retimed: no subject motion, no pan
CORNERS = 400  # corners tracked per frame for the camera's movement
HELD, STILL_SHARE = 0.1, 0.2  # a corner that moves under HELD pixels holds still; a tripod's corners move 0.02 to 0.05,
#                              and the steadiest hand moves all of them 0.1 or more


def identity(sc: dict) -> dict:
    from . import smooth
    return {"focus": VERSION, "smooth": smooth.VERSION, **view.identity(sc)}


def camera(last: np.ndarray, y: np.ndarray) -> np.ndarray | None:
    """The camera's movement from one frame to the next, as a 2x3 transform, or None when too few corners hold."""
    import cv2
    corners = cv2.goodFeaturesToTrack(last, CORNERS, 0.01, 8)
    if corners is None or len(corners) < 20:
        return None
    moved, ok, _ = cv2.calcOpticalFlowPyrLK(last, y, corners, None, winSize=(21, 21), maxLevel=3)
    ok = ok.ravel() == 1
    if ok.sum() < 20:
        return None
    if (np.linalg.norm((moved - corners)[ok].reshape(-1, 2), axis=1) < HELD).mean() >= STILL_SHARE:
        return np.float32([[1, 0, 0], [0, 1, 0]])
    return cv2.estimateAffinePartial2D(corners[ok], moved[ok], method=cv2.RANSAC, ransacReprojThreshold=1.0)[0]


def grid_sharpness(clip: Path, sc: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Log sharpness per region per frame, a coarse thumbnail per frame, how far the camera moved the picture (pixels
    per frame) and how much the thumbnail changed with that movement taken out."""
    import cv2
    h = view.size(sc, W)[1]
    p = subprocess.Popen(view.grey(clip, sc, W), stdout=subprocess.PIPE)
    sharp, thumbs, pans, change, last = [], [], [], [], None
    small = lambda f: cv2.resize(f, (W // 10, h // 10), interpolation=cv2.INTER_AREA).astype(np.float32)
    corners = np.float32([[0, 0], [W, 0], [W, h], [0, h]]).reshape(-1, 1, 2)
    while len(b := p.stdout.read(W * h)) == W * h:
        grey = np.frombuffer(b, np.uint8).reshape(h, W)
        if last is None:
            pans.append(0.0), change.append(0.0)
        else:
            A = camera(last, grey)
            if A is None:  # nothing to track: a blank or blurred frame, measured as it changed
                pans.append(0.0), change.append(float(np.abs(small(grey) - small(last)).mean()))
            else:
                pans.append(float(np.abs(cv2.transform(corners, A) - corners).mean()))
                held = cv2.warpAffine(last, A, (W, h), borderMode=cv2.BORDER_REPLICATE)
                change.append(float(np.abs(small(grey) - small(held))[2:-2, 2:-2].mean()))  # edges the camera revealed left out
        last = grey
        y = grey.astype(np.float32)
        lap = 4 * y[1:-1, 1:-1] - y[:-2, 1:-1] - y[2:, 1:-1] - y[1:-1, :-2] - y[1:-1, 2:]
        th, tw = (h - 2) // GY, (W - 2) // GX
        sharp.append(np.log(lap[:th * GY, :tw * GX].reshape(GY, th, GX, tw).var(axis=(1, 3)) + 1).ravel())
        thumbs.append(y[:h // 10 * 10].reshape(h // 10, 10, W // 10, 10).mean(axis=(1, 3)))
    p.wait()
    return np.array(sharp), np.array(thumbs), np.array(pans), np.array(change)


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
    sharp, thumbs, pans, change = grid_sharpness(clip, sc)
    found = pulls(sharp, thumbs, pans, fps)
    for p in found:
        still = p["motion"] <= STILL_MOTION and p["pan"] <= STILL_PAN
        p["smooth"] = smooth.best(clip, sc, sharp, *p["frames"]) if still else None
    per = max(1, round(fps))
    second = lambda v: [round(float(v[i:i + per].mean()), 2) for i in range(1, len(v), per)]
    # Per second beside motion and camera: how sharp the frame is (mean log sharpness over the regions) and how
    # bright it is (mean grey level). Computed on read, usable() and cutpoints() score every second from these.
    return {"pulls": found, "motion": second(change), "camera": second(pans),
            "sharp": second(sharp.mean(1)) if len(sharp) else [], "light": second(thumbs.mean((1, 2))) if len(thumbs) else []}


MOVING = 0.35  # thumbnail change per frame (grey levels) at which something in a locked-off shot is moving: a still
#               machine read 0.1, a gripper working 0.4 to 0.5, a gantry swinging across the frame 1.4 to 1.8
MOVING_SECONDS = 2  # shortest moving stretch worth listing
STEADY = 0.08  # camera movement (pixels per frame, W wide) up to which the camera is held still: a tripod reads 0.01
#              to 0.05, and the steadiest hand 0.1


SHARP_DROP = 0.6  # log sharpness below the clip's own median at which a second reads defocused: a pull worth
#                 cutting on changes 1.2 or more (PULL_MIN), so half that is a frame on its way out of focus
HELD_MAX = 0.5  # camera movement above the steadiest hand (0.1 to 0.5 reads held, 0.5 to 2 shaky)
DARK = 4.0  # mean grey level below which a second is black: lens cap, covered lens, fade floor
USABLE_SECONDS = 2  # shortest usable stretch worth offering an edit, as with MOVING_SECONDS


def usable(sc: dict) -> list[tuple[int, float]]:
    """Stretches of at least USABLE_SECONDS whole seconds an edit can cut inside: sharp against the clip's own
    median, the camera held rather than shaking, and not black. One bad second inside a run is bridged; the last
    stretch may end mid-second. Computed from the focus facts, never stored."""
    f, end = sc.get("focus", {}), sc["facts"]["duration"]
    sharp, camera, light = f.get("sharp", []), f.get("camera", []), f.get("light", [])
    if not sharp:
        return []
    floor = float(np.median(sharp)) - SHARP_DROP
    ok = [sharp[s] >= floor and (s >= len(camera) or camera[s] <= HELD_MAX) and (s >= len(light) or light[s] >= DARK)
          for s in range(len(sharp))]
    runs, start, last_good = [], None, None
    for s, good in enumerate(ok + [False]):
        if good:
            start, last_good = (s if start is None else start), s
        elif start is not None and s - last_good > 1:  # second bad second in a row ends the run at its last good one
            if min(last_good + 1, end) - start >= USABLE_SECONDS:
                runs.append((start, round(min(last_good + 1, end), 2)))
            start, last_good = None, None
    if start is not None and min(last_good + 1, end) - start >= USABLE_SECONDS:
        runs.append((start, round(min(last_good + 1, end), 2)))
    return runs


def cutpoints(sc: dict) -> list[dict]:
    """Frames an edit can cut on, each with why and a score: a pull about to start or just settled, a pause in
    speech, the edge of a moving stretch, or a lull in the motion with the camera held. Computed from the focus
    and transcript facts, never stored. Points within a quarter second keep the better score."""
    f, out = sc.get("focus", {}), []
    for p in f.get("pulls", []):
        out += [{"t": p["start"], "score": 0.9, "why": "pull starts"}, {"t": p["end"], "score": 0.9, "why": "pull settled"}]
    words = sc.get("transcript", {}).get("words", [])
    for a, b in zip(words, words[1:]):
        if b["start"] - a["end"] >= 0.6:
            out.append({"t": round((a["end"] + b["start"]) / 2, 2), "score": 0.8, "why": "speech pause"})
    for a, b in moving(sc):
        out += [{"t": float(a), "score": 0.7, "why": "movement starts"}, {"t": float(b), "score": 0.7, "why": "movement ends"}]
    motion, camera, last_lull = f.get("motion", []), f.get("camera", []), -2
    for s in range(1, len(motion) - 1):
        if (motion[s] < motion[s - 1] and motion[s] <= motion[s + 1] and s - last_lull >= 2
                and s < len(camera) and camera[s] <= HELD_MAX):
            out.append({"t": float(s), "score": 0.5, "why": "motion lull"})
            last_lull = s
    kept = []
    for c in sorted(out, key=lambda c: c["t"]):
        if kept and c["t"] - kept[-1]["t"] < 0.25:
            kept[-1] = max(kept[-1], c, key=lambda c: c["score"])
        else:
            kept.append(c)
    return kept


def moving(sc: dict) -> list[tuple[int, float]]:
    """Stretches of at least MOVING_SECONDS whole seconds in which something moves in front of a still camera; the
    last may end mid-second."""
    end, runs, start = sc["facts"]["duration"], [], None
    f = sc.get("focus", {})
    for s, (m, c) in enumerate(list(zip(f.get("motion", []), f.get("camera", []))) + [(0.0, 0.0)]):
        if m >= MOVING and c <= STEADY:
            start = s if start is None else start
        elif start is not None:
            if min(s, end) - start >= MOVING_SECONDS:
                runs.append((start, round(min(s, end), 2)))
            start = None
    return runs
