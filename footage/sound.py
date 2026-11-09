"""How loud a clip is, second by second: K-weighted loudness (LUFS) and the true peak, so an edit can ride levels
by measurement, find the dead air, and see where the recorder clipped.

The sound is decoded once, mono at 48 kHz, and filtered with the two BS.1770 K-weighting stages. Each second's
loudness is its mean square through that filter; its peak is the largest sample. Silence and clipping are read off
those arrays when asked, never stored. A clip shot without sound holds two empty arrays."""
import subprocess
from pathlib import Path

import numpy as np
from scipy.signal import lfilter

from . import probe

VERSION = 1  # bump when the weighting, rate or arrays change meaning
RATE = 48000
# BS.1770 K-weighting at 48 kHz: a shelf that counts the head's presence boost, then a high-pass for the lows
# the ear discounts. The -0.691 dB is the calibration that makes a full-scale 1 kHz tone read its level.
SHELF = ([1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585])
HIGHPASS = ([1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621])
QUIET = -55.0  # LUFS at or under which a second of camera audio carries nothing an edit keeps; to be checked
#              against the library's distribution after the first sound run, like focus.MOVING was
CLIP = 0.999  # a sample this near full scale: the recorder's ceiling, whatever its meter said
QUIET_SECONDS = 2  # shortest dead stretch worth listing


def identity(sc: dict) -> dict:
    return {"sound": VERSION}


def sound(clip: Path, sc: dict) -> dict:
    """Per second: K-weighted LUFS and peak sample, of the clip's sound decoded mono at 48 kHz."""
    if not any(s["codec_type"] == "audio" for s in probe.ffprobe(clip)["streams"]):
        return {"lufs": [], "peak": []}
    raw = subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(clip), "-vn", "-ac", "1", "-ar", str(RATE),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
    weighted = lfilter(*HIGHPASS, lfilter(*SHELF, x))
    n = len(x) // RATE
    watts = (weighted[:n * RATE].reshape(n, RATE) ** 2).mean(1) if n else np.zeros(0)
    return {"lufs": [round(float(-0.691 + 10 * np.log10(max(w, 1e-12))), 1) for w in watts],
            "peak": [round(float(v), 3) for v in (np.abs(x[:n * RATE].reshape(n, RATE)).max(1) if n else [])]}


def loudness(sc: dict) -> float | None:
    """The clip's integrated loudness: the energy mean of its seconds, or None when it has no sound."""
    rows = sc.get("sound", {}).get("lufs") or []
    return round(float(10 * np.log10(np.mean(10 ** (np.array(rows) / 10)))), 1) if rows else None


def silence(sc: dict) -> list[tuple[int, float]]:
    """Stretches of at least QUIET_SECONDS whole seconds at or under QUIET; the last may end mid-second."""
    rows, end, runs, start = sc.get("sound", {}).get("lufs", []), sc["facts"]["duration"], [], None
    for s, level in enumerate([*rows, 0.0]):
        if level <= QUIET and s < len(rows):
            start = s if start is None else start
        elif start is not None:
            if min(s, end) - start >= QUIET_SECONDS:
                runs.append((start, round(min(s, end), 2)))
            start = None
    return runs


def clipped(sc: dict) -> list[int]:
    """The seconds whose peak reached the recorder's ceiling."""
    return [s for s, p in enumerate(sc.get("sound", {}).get("peak", [])) if p >= CLIP]
