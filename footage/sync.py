"""Where one recording sits inside another's time: the offset between two recordings of one event, from their sound.

The envelopes of the two mono waveforms are cross-correlated coarse (100 Hz), then the waveforms themselves in a
window around the coarse answer, which pins the offset well inside one frame. With --write, each clip's sidecar
records the pair: under the other clip's day/name, where the other's first second falls in this clip (`at`, which
negates between the two) and how strong the match is (`score`, the correlation peak over its median: the same event
recorded twice measures far clear of unrelated sound).

python -m footage.sync A.MP4 B.MP4 [--write]
"""
import argparse
from pathlib import Path

import numpy as np
from scipy.signal import correlate, correlation_lags

from . import idle, library, sidecar
from .transcribe.hear import RATE, audio

COARSE = 100  # envelope samples per second for the first pass
REFINE = 0.25  # seconds either side of the coarse answer that the full-rate pass searches


def envelope(x: np.ndarray) -> np.ndarray:
    """The waveform's loudness outline at COARSE Hz: mean square in each step, square root, mean removed."""
    step = RATE // COARSE
    n = len(x) // step
    e = np.sqrt((x[:n * step].reshape(n, step) ** 2).mean(1) + 1e-12)
    return e - e.mean()


def offset(a: Path, b: Path) -> tuple[float, float]:
    """(where b's start falls in a's time, in seconds, and the match score). Negative: b started first."""
    xa, xb = audio(a), audio(b)
    if not len(xa) or not len(xb):
        raise SystemExit("sync needs sound in both recordings")
    ea, eb = envelope(xa), envelope(xb)
    c = correlate(ea, eb, mode="full", method="fft")
    lag = float(correlation_lags(len(ea), len(eb))[int(np.argmax(c))]) / COARSE
    score = float(c.max() / (np.median(np.abs(c)) + 1e-12))
    # Refine at the full rate: correlate the stretch of a the coarse answer points at with b's first seconds.
    head = xb[:RATE * 5] - xb[:RATE * 5].mean()
    lo, hi = max(int((lag - REFINE) * RATE), 0), min(int((lag + REFINE) * RATE) + len(head), len(xa))
    if hi - lo > len(head):
        window = xa[lo:hi] - xa[lo:hi].mean()
        fine = correlate(window, head, mode="valid", method="fft")
        lag = (lo + int(np.argmax(fine))) / RATE
    return round(lag, 3), round(score, 1)


def store(a: Path, b: Path, at: float, score: float) -> None:
    """Write the pair into both sidecars, through sidecar.update: in a's, where b starts; in b's, where a starts."""
    for clip, other, mine in ((a, b, at), (b, a, -at)):
        name = library.name_of(other)
        sidecar.update(clip, lambda sc, name=name, mine=mine: None if sc is None else
                       {**sc, "sync": {**sc.get("sync", {}), name: {"at": mine, "score": score}}})


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="footage.sync")
    ap.add_argument("a", type=Path)
    ap.add_argument("b", type=Path)
    ap.add_argument("--write", action="store_true", help="record the pair in both sidecars")
    a = ap.parse_args()
    idle()
    at, score = offset(a.a, a.b)
    print(f"{a.b.name} starts at {at:.3f}s in {a.a.name} (score {score})")
    if a.write:
        if sidecar.read(a.a) is None or sidecar.read(a.b) is None:
            raise SystemExit("--write needs both clips filed (sidecars present)")
        store(a.a, a.b, at, score)
        print("written to both sidecars")
