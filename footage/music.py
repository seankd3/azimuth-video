"""A music track's beats and energy, for cutting picture to it.

python -m footage.music TRACK  prints the tempo, the beats, and the loudness envelope by bar.
"""
import sys
from pathlib import Path

import numpy as np


def analyse(track: Path) -> dict:
    """Tempo, beat times (s), bar starts, loudness per bar and per second, in dB below the loudest."""
    import librosa
    y, sr = librosa.load(str(track), sr=22050, mono=True)
    tempo, frames = librosa.beat.beat_track(y=y, sr=sr, units="frames", tightness=120)
    found = librosa.frames_to_time(frames, sr=sr)
    # Generated and most produced music holds its tempo: extend the tracked beats as a steady grid over the whole
    # track, so quiet passages without percussion still have beats to cut on.
    period = float(np.median(np.diff(found))) if len(found) > 1 else 60 / float(np.atleast_1d(tempo)[0])
    first = found[0] - period * np.floor(found[0] / period) if len(found) else 0.0
    beats = np.arange(first, len(y) / sr, period)
    rms = librosa.feature.rms(y=y)[0]
    t = librosa.frames_to_time(np.arange(len(rms)), sr=sr)
    # A bar is four beats; start the grid on the beat after which the loudness rises most (the likeliest downbeat).
    phase = max(range(4), key=lambda k: float(np.mean([np.interp(b, t, rms) for b in beats[k::4]])))
    bars = beats[phase::4]
    edges = np.append(bars, len(y) / sr)
    level = [float(rms[(t >= a) & (t < b)].mean()) if ((t >= a) & (t < b)).any() else 0.0 for a, b in zip(edges, edges[1:])]
    db = 20 * np.log10(np.maximum(level, 1e-6) / max(max(level), 1e-6))
    second = [float(rms[(t >= s) & (t < s + 1)].mean()) for s in range(int(len(y) / sr))]
    return {"tempo": 60 / period, "duration": len(y) / sr,
            "loudness_db": [round(float(v), 1) for v in 20 * np.log10(np.maximum(second, 1e-6) / max(second))],
            "beats": [round(float(b), 3) for b in beats], "bars": [round(float(b), 3) for b in bars],
            "bar_db": [round(float(v), 1) for v in db]}


if __name__ == "__main__":
    a = analyse(Path(sys.argv[1]))
    print(f"tempo {a['tempo']:.1f} bpm, {a['duration']:.1f} s, {len(a['beats'])} beats, first beat {a['beats'][0]}s")
    print("loudness by second (dB below the loudest):")
    print("  " + " ".join(f"{v:.0f}" for v in a["loudness_db"]))
