"""Measured picture facts for grading and picking shots: exposure and white balance in scene light, sharpness, motion."""
import subprocess
from pathlib import Path

import numpy as np

from . import color, face, view

W = 1280  # analysis width, desqueezed so faces have their real shape
DETAIL = 3200  # width of the frames faces are recognized from
VERSION = 8  # bump when a measurement changes meaning, so the measure pass redoes every clip
GATES = (0.4, 0.25, 0.15, 0.08)  # chroma limits the white-balance search narrows through
MIN_SHARE = 0.01  # least share of the moderately bright pixels a white-balance estimate may rest on


def identity(sc: dict) -> dict:
    return {"measure": VERSION, **face.identity(), **view.identity(sc), **color.identity(sc)}


def frames(clip: Path, sc: dict, t: float, n: int = 1, w: int = W) -> np.ndarray:
    h = view.size(sc, w)[1]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-threads", "1", "-ss", f"{t:.3f}", "-i", str(clip), "-frames:v", str(n),
                          "-vf", view.cpu(sc, w), "-pix_fmt", "rgb48le", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype="<u2").reshape(-1, h, w, 3).astype(np.float32) / 65535


def neutral(lin: np.ndarray) -> dict:
    """The colour grey records as in these scene-linear frames, and the evidence for it.

    The estimate averages moderately bright pixels that are near-neutral once the current estimate is removed (walls,
    tables, shirts), narrowing through GATES. It starts from the camera's own balance, the one outside witness: under
    it grey already records as grey, so a shot full of one strong colour can't pass that colour for grey. The evidence
    is `gate`, the tightest chroma limit the search got through, and `share`, the part of the moderately bright pixels
    within that limit of the estimate. When nothing near the camera's balance looks grey (a close-up of one colour, or
    a camera set for very different light; the pixels can't tell which) there is no estimate: gate None, and the
    camera's balance stands."""
    rgb, yy = lin.reshape(-1, 3), color.luminance(lin).reshape(-1)
    lo, hi = np.percentile(yy, [40, 97])
    band = rgb[(yy > lo) & (yy < hi)]
    found, n = {"rgb": np.ones(3), "share": 0.0, "gate": None}, np.ones(3)
    for limit in GATES:
        c = band / n
        near = (c.max(1) - c.min(1)) / np.maximum(c.max(1), 1e-5) < limit
        if not len(band) or near.mean() < MIN_SHARE:
            break
        n = band[near].mean(0)
        found = {"rgb": n / n[1], "share": float(near.mean()), "gate": limit}
    return found


def measure(clip: Path, sc: dict) -> dict:
    f, a = sc["facts"], sc["assumed"]
    n = 6
    times = [round(f["duration"] * (i + 0.5) / n, 2) for i in range(n)]
    pairs = [frames(clip, sc, t, 2) for t in times]  # two consecutive frames per sample: the second gives motion
    code = np.stack([p[0] for p in pairs])
    lin = color.to_linear_709(code, a)
    y = np.clip(color.luminance(lin), 1e-5, None)
    white = neutral(lin)
    # Sharpness: variance of the Laplacian of display luma, centre crop (where focus usually is).
    disp = color.luminance(color.tone(lin))
    c = disp[:, disp.shape[1] // 4: -disp.shape[1] // 4, disp.shape[2] // 4: -disp.shape[2] // 4]
    lap = c[:, 1:-1, 1:-1] * 4 - c[:, :-2, 1:-1] - c[:, 2:, 1:-1] - c[:, 1:-1, :-2] - c[:, 1:-1, 2:]
    second = color.luminance(color.tone(color.to_linear_709(np.stack([p[-1] for p in pairs]), a)))
    # Every face in every sample frame (who, and how lit), and a summary of the largest: the shot's subject, if any.
    found = [face.find(frame, color.to_linear_709(frames(clip, sc, t, 1, DETAIL)[0], a))
             for t, frame in zip(times, lin)]
    faces = [{"t": t, **x} for t, frame_faces in zip(times, found) for x in frame_faces]
    largest = [frame_faces[0] for frame_faces in found if frame_faces]
    seen = None
    if largest:
        med = lambda k: round(float(np.median([x[k] for x in largest])), 2)
        fp = np.median([x["print"] for x in largest], axis=0)
        seen = {"in_frames": len(largest), "of": n, "height": med("height"), "key_stops": med("key_stops"),
                "fill_stops": med("fill_stops"), "print": [round(float(v), 3) for v in fp / np.linalg.norm(fp)]}
    return {
        "frames_at": times,
        "exposure_stops": round(float(np.log2(np.exp(np.log(y).mean()) / 0.18)), 2),
        "highlights_clipped_pct": round(float((code.max(-1) > 0.985).mean() * 100), 2),
        "shadows_crushed_pct": round(float((y < 0.002).mean() * 100), 2),
        "neutral_rgb": [round(float(v), 3) for v in white["rgb"]],
        "neutral_share": round(white["share"], 3),
        "neutral_gate": white["gate"],
        "sharpness": round(float(lap.var(axis=(1, 2)).mean() * 1e4), 2),
        "motion": round(float(np.abs(second - disp).mean() * 100), 2),
        "face": seen,
        "faces": faces,
    }
