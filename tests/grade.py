"""Grade rules on measured facts alone, no pictures: which shots the natural look shows as dark.

A daylight shot with a bright sky filling the frame was once shown as a night: the look's key brightens a high-key
frame, and brightening was read as darkness. The camera's exposure, where the file records it, settles day from night.

Run: .venv/bin/python tests/grade.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from footage import grade  # noqa: E402


def shot(avg: float, low: float, high: float, **notes) -> dict:
    return {"facts": {"notes": notes}, "measured": {"exposure_stops": avg, "range_stops": [low, high]}}


CASES = [  # what, the shot, dark?
    ("a blue sky filling the frame, auto exposure", shot(0.02, -5.42, 1.44), False),
    ("the same sky, 8K RAW at ISO 800, 1/250, f/22", shot(0.02, -5.42, 1.44, iso=800, exposure_time=0.004, f_number=22), False),
    ("daylight a stop under, the exposure recorded", shot(-1.0, -6.0, 0.5, iso=800, exposure_time=0.004, f_number=22), False),
    ("a night street, 1/50 f/2.8 ISO 3200", shot(0.5, -6.0, 3.0, iso=3200, exposure_time=0.02, f_number=2.8), True),
    ("a dim room, exposure not recorded, 2.5 stops under", shot(-2.5, -7.0, 1.0), True),
    ("an exposed-to-the-right room, exposure not recorded", shot(1.85, -4.0, 4.5), False),
]


def main() -> int:
    look, bad = grade.look("natural"), 0
    for what, sc, want in CASES:
        got = grade.dark(sc, look)
        bad += got != want
        print(f"{'PASS' if got == want else 'FAIL'} {what}: {'dark' if got else 'not dark'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
