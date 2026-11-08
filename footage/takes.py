"""Takes: clips shot one after another from one camera position, and the best of them.

A shoot often repeats a shot: the camera stays put and rolls again, waiting for a machine to move or a person to get it
right. Two clips are one angle when their backgrounds line up: ORB features of three frames of each (at 15%, 50% and
85% of the clip) are matched and a homography fitted, and one angle needs at least SAME_POINTS points that agree on a
homography moving the frame by at most SAME_SHIFT of its width. A tripod nudged or a handheld frame drifting stays one
angle; a new framing of the same machine doesn't. The `angle` pass stores each clip's features, so grouping a day
decodes nothing.

The takes of an angle are consecutive clips of one day: a clip joins the takes before it when it is one angle with any
of them and was shot within GAP seconds of the last. The best take is the last one, unless it lacks the action: it is the
last take that moves for at least half as long as the take that moves longest (focus.moving). A clip shot once is its
own best take.

python -m footage.takes [--day DAY] [--json]
"""
import argparse
import base64
import json
import subprocess
from datetime import datetime
from pathlib import Path

import numpy as np

from . import focus, library, passes, sidecar, view

VERSION = 1
W = 480  # frames are matched this many pixels wide, desqueezed
POINTS = 500  # ORB features kept per frame
AT = (0.15, 0.5, 0.85)
# Calibrated on 115 clips of one shoot, checked by eye: one angle matched 100 to 1100 points at 2000 features with the
# frame moved 0 to 0.07 of its width; another framing of the same machine 60 to 200 points but moved 0.1 to 0.6. At 500
# features the groups were the same from 15 to 20 points.
SAME_POINTS, SAME_SHIFT = 20, 0.08
GAP = 20 * 60  # takes of one shot follow each other: the longest wait between two seen was 16 minutes


def identity(sc: dict) -> dict:
    return {"angle": VERSION, **view.identity(sc)}


def pack(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def angle(clip: Path, sc: dict) -> dict:
    """The `angle` section: the ORB features of three frames."""
    import cv2
    w, h = view.size(sc, W)
    d, orb, frames = sc["facts"]["duration"], cv2.ORB_create(POINTS), []
    for at in AT:
        t = min(at * d, max(d - 0.2, 0))
        raw = subprocess.run(view.grey(clip, sc, W, start=t, frames=1), capture_output=True, check=True).stdout
        points, desc = orb.detectAndCompute(np.frombuffer(raw[:w * h], np.uint8).reshape(h, w), None)
        xy = np.array([p.pt for p in points], np.float32).reshape(-1, 2)
        frames.append({"t": round(t, 2), "xy": pack(np.round(xy * 8).astype(np.uint16)),
                       "orb": pack(desc if desc is not None else np.zeros((0, 32), np.uint8))})
    return {"width": w, "height": h, "frames": frames}


def features(section: dict) -> list[tuple[np.ndarray, np.ndarray]]:
    return [(np.frombuffer(base64.b64decode(f["xy"]), np.uint16).reshape(-1, 2).astype(np.float32) / 8,
             np.frombuffer(base64.b64decode(f["orb"]), np.uint8).reshape(-1, 32)) for f in section["frames"]]


def same(a: dict, b: dict) -> bool:
    """Whether two clips' backgrounds line up: some pair of their frames has SAME_POINTS points agreeing on one
    homography that moves the frame by at most SAME_SHIFT of its width."""
    import cv2
    match = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    w, h = a["width"], a["height"]
    corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
    for xa, da in features(a):
        for xb, db in features(b):
            m = match.match(da, db) if min(len(da), len(db)) >= SAME_POINTS else []
            if len(m) < SAME_POINTS:
                continue
            # Frames of one angle agree on most matches, so a few hundred tries find it; more only fail slower.
            H, agree = cv2.findHomography(xa[[x.queryIdx for x in m]], xb[[x.trainIdx for x in m]], cv2.RANSAC, 4.0, maxIters=300)
            if H is not None and agree.sum() >= SAME_POINTS and np.abs(cv2.perspectiveTransform(corners, H) - corners).mean() / w <= SAME_SHIFT:
                return True
    return False


def moves(sc: dict) -> float:
    return sum(e - s for s, e in focus.moving(sc))


def best(takes: list[tuple[Path, dict]]) -> tuple[Path, str]:
    """The best of an angle's takes, and why."""
    time = [moves(sc) for _, sc in takes]
    pick = max(i for i, t in enumerate(time) if t >= max(time) / 2)
    if len(takes) == 1:
        return takes[0][0], "shot once"
    if pick == len(takes) - 1:
        return takes[pick][0], "the last take"
    return takes[pick][0], f"the last that moves: {time[pick]:g} s, the last take {time[-1]:g} s"


def angles(clips: list[tuple[Path, dict]]) -> list[dict]:
    """Each angle's takes in shooting order, and its best, from clips with current sidecars (passes.fresh). A clip
    without a current angle section is an angle of its own."""
    shot = lambda sc: datetime.fromisoformat(sc["facts"]["captured_utc"]).timestamp()
    runs: list[list[tuple[Path, dict]]] = []
    for clip, sc in sorted(clips, key=lambda c: (c[0].parent.name, shot(c[1]))):
        last = runs[-1] if runs else None
        if (last and "angle" in sc and last[-1][0].parent == clip.parent and shot(sc) - shot(last[-1][1]) <= GAP
                and any("angle" in s and same(s["angle"], sc["angle"]) for _, s in last)):
            last.append((clip, sc))
        else:
            runs.append([(clip, sc)])
    out = []
    for run in runs:
        pick, why = best(run)
        out.append({"takes": [c for c, _ in run], "best": pick, "why": why})
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="footage.takes")
    ap.add_argument("--library", type=Path, default=Path.home() / "Videos/Library")
    ap.add_argument("--day", help="shooting day, YYYY-MM-DD")
    ap.add_argument("--json", action="store_true", help="for an agent")
    a = ap.parse_args()
    clips = [(c, passes.fresh(c, sc)[0]) for c in library.clips(a.library)
             if (not a.day or c.parent.name == a.day) and (sc := sidecar.read(c)) is not None]
    found = angles(clips)
    name = lambda c: f"{c.parent.name}/{c.stem}"
    if a.json:
        print(json.dumps([{"takes": [name(c) for c in g["takes"]], "best": name(g["best"]), "why": g["why"]} for g in found], indent=1))
    else:
        for g in found:
            if len(g["takes"]) > 1:
                print(" ".join(f"[{c.stem}]" if c == g["best"] else c.stem for c in g["takes"]), f" best: {g['why']}")
        many = sum(len(g["takes"]) > 1 for g in found)
        print(f"{len(found)} angles from {len(clips)} clips; {many} shot more than once")
    if missing := sum("angle" not in sc for _, sc in clips):
        print(f"{missing} clips have no current angle section, each counted as an angle of its own: run python -m footage")
