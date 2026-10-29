"""Measured picture facts for grading and picking shots: exposure and white balance in scene light, sharpness, motion."""
import subprocess
from pathlib import Path

import numpy as np

from . import color, face

W = 1280  # analysis width, desqueezed so faces have their real shape
DETAIL = 3200  # width of the frames faces are recognized from
VERSION = 8  # bump when a measurement changes meaning, so the measure pass redoes every clip


def frames(clip: Path, t: float, f: dict, n: int = 1, squeeze: float = 1.0, w: int = W) -> np.ndarray:
    h = round(w * f["height"] / (f["width"] * squeeze) / 2) * 2
    raw = subprocess.run(["ffmpeg", "-v", "error", "-threads", "1", "-ss", f"{t:.3f}", "-i", str(clip), "-frames:v", str(n),
                          "-vf", f"scale={w}:{h}", "-pix_fmt", "rgb48le", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype="<u2").reshape(-1, h, w, 3).astype(np.float32) / 65535


def measure(clip: Path, sc: dict) -> dict:
    f, a = sc["facts"], sc["assumed"]
    n = 6
    times = [round(f["duration"] * (i + 0.5) / n, 2) for i in range(n)]
    pairs = [frames(clip, t, f, 2, a["squeeze"] or 1.0) for t in times]  # two consecutive frames per sample: the second gives motion
    code = np.stack([p[0] for p in pairs])
    lin = color.to_linear_709(code, a)
    y = np.clip(color.luminance(lin), 1e-5, None)
    # White balance: the average colour of moderately bright pixels that are near-neutral once the current estimate
    # is removed (walls, tables, shirts). The search starts from the camera's own balance, under which grey already
    # records as grey, and narrows; starting from the frame's average colour let a big red machine pass for grey.
    rgb = lin.reshape(-1, 3)
    yy = y.reshape(-1)
    lo, hi = np.percentile(yy, [40, 97])
    band = rgb[(yy > lo) & (yy < hi)]
    neutral = np.ones(3)
    for limit in (0.4, 0.25, 0.15, 0.08):
        c = band / neutral
        chroma = (c.max(1) - c.min(1)) / np.maximum(c.max(1), 1e-5)
        if (chroma < limit).sum() < 500:
            break
        neutral = band[chroma < limit].mean(0)
    neutral = neutral / neutral[1]
    # Sharpness: variance of the Laplacian of display luma, centre crop (where focus usually is).
    disp = color.luminance(color.tone(lin))
    c = disp[:, disp.shape[1] // 4: -disp.shape[1] // 4, disp.shape[2] // 4: -disp.shape[2] // 4]
    lap = c[:, 1:-1, 1:-1] * 4 - c[:, :-2, 1:-1] - c[:, 2:, 1:-1] - c[:, 1:-1, :-2] - c[:, 1:-1, 2:]
    second = color.luminance(color.tone(color.to_linear_709(np.stack([p[-1] for p in pairs]), a)))
    # Every face in every sample frame (who, and how lit), and a summary of the largest: the shot's subject, if any.
    found = [face.find(frame, color.to_linear_709(frames(clip, t, f, 1, a["squeeze"] or 1.0, DETAIL)[0], a))
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
        "v": VERSION,
        "frames_at": times,
        "exposure_stops": round(float(np.log2(np.exp(np.log(y).mean()) / 0.18)), 2),
        "highlights_clipped_pct": round(float((code.max(-1) > 0.985).mean() * 100), 2),
        "shadows_crushed_pct": round(float((y < 0.002).mean() * 100), 2),
        "neutral_rgb": [round(float(v), 3) for v in neutral],
        "sharpness": round(float(lap.var(axis=(1, 2)).mean() * 1e4), 2),
        "motion": round(float(np.abs(second - disp).mean() * 100), 2),
        "face": seen,
        "faces": faces,
    }
