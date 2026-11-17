"""Clipped light stays neutral through the white balance: a tabletop under coloured lights, balanced with a strong blue
correction, turned its hot spots lime, because green and blue had clipped and the balance scaled them like the rest.
Light the camera couldn't hold fades to neutral at its brightness; light below the clip keeps its colour.

Run: .venv/bin/python tests/unclip.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from footage import color, grade  # noqa: E402

GAIN = np.array([1 / 1.2, 1.0, 1 / 2.1])  # the blue-lit table's balance: blue divided by 2.1


def chroma(lin: np.ndarray) -> float:
    return float((lin.max() - lin.min()) / max(lin.max(), 1e-9))


CASES = [  # what, code values, balanced colour, the most chroma it may keep, the least
    ("a hot spot clipped in green and blue", [0.95, 1.0, 1.0], [8.0, 9.0, 9.0] * GAIN, 0.02, 0.0),
    ("a lamp clipped in all three", [1.0, 1.0, 1.0], [9.0, 9.0, 9.0] * GAIN, 0.02, 0.0),
    ("a lit grey housing, well below the clip", [0.64, 0.66, 0.75], [1.9, 1.9, 3.9] * GAIN, 1.0, 0.03),
    ("a saturated orange seal below the clip", [0.80, 0.62, 0.45], [6.0, 2.0, 0.6], 1.0, 0.6),
]


def main() -> int:
    bad = 0
    for what, code, lin, most, least in CASES:
        out = grade.unclip(np.array(lin)[None], np.array(code)[None])[0]
        c = chroma(out)
        kept = abs(color.luminance(out) - color.luminance(np.array(lin))) < 1e-9
        ok = least <= c <= most and kept
        bad += not ok
        print(f"{'PASS' if ok else 'FAIL'} {what}: chroma {chroma(np.array(lin)):.2f} -> {c:.2f}{'' if kept else ', luminance moved'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
