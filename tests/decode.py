"""CPU decode threads by frame size: a render of an 8K RAW development was stopped at the media lane's memory ceiling
three times, its decoder holding 8.4 GB of frames queued between ffmpeg's stages, at 8 threads and at 4, because it
decoded faster than the grade took them. A frame that big gets 2 threads, slower than the grade; a small frame, 8.

Run: .venv/bin/python tests/decode.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from footage import render  # noqa: E402

CASES = [  # what, frame size, format, the most threads it may take, the fewest
    ("an 8K 4:4:4 12-bit RAW development", (8192, 4320), "yuv444p12le", 2, 1),
    ("a 6.5K 4:2:2 10-bit camera clip", (6554, 2160), "yuv422p10le", 8, 8),
    ("a 4K 4:2:0 8-bit clip", (3840, 2160), "yuv420p", 8, 8),
]


def main() -> int:
    bad = 0
    for what, size, fmt, most, fewest in CASES:
        n = render.decode_threads(size, fmt)
        ok = fewest <= n <= most
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {n} threads: {what}")
    return bool(bad)


if __name__ == "__main__":
    sys.exit(main())
