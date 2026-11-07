"""Set what a clip's file doesn't record about it, in its sidecar's `assumed` section: lens squeeze, log curve and
gamut, and neutral_rgb (the colour grey records as; [1, 1, 1] keeps the
camera's balance, null goes back to the measured one). Anything read from a changed value is redone by the next run.

python -m footage.assume 2026-10-29 squeeze=1.6                 every clip of a shooting day
python -m footage.assume CLIP0101 2026-10-28/CLIP0042.MP4 neutral_rgb=[1,1,1]
"""
import argparse
import json
from pathlib import Path

from . import library, sidecar

KEYS = ("squeeze", "log", "gamut", "neutral_rgb")


def value(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text  # a bare word, like a log curve name


def targets(lib: Path, names: list[str]) -> list[Path]:
    """Clips by shooting day, else by DAY/FILE, or by file name or stem when that names exactly one clip."""
    every, out = library.clips(lib), []
    for n in names:
        found = [c for c in every if c.parent.name == n] or [c for c in every if n in (library.name_of(c), c.name, c.stem)]
        if len(found) != 1 and not (found and found[0].parent.name == n):
            raise SystemExit(f"{n}: {'no clip' if not found else 'more than one clip; use DAY/FILE'}")
        out += found
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="footage.assume")
    ap.add_argument("args", nargs="+", help="clips or days, then KEY=VALUE settings")
    ap.add_argument("--library", type=Path, default=Path.home() / "Videos/Library")
    a = ap.parse_args()
    settings = dict(x.split("=", 1) for x in a.args if "=" in x)
    unknown = set(settings) - set(KEYS)
    if not settings or unknown:
        raise SystemExit(f"set one or more of {', '.join(KEYS)}" + (f"; not {', '.join(sorted(unknown))}" if unknown else ""))
    settings = {k: value(v) for k, v in settings.items()}
    clips = targets(a.library, [x for x in a.args if "=" not in x])
    done = [c for c in clips if sidecar.update(c, lambda sc: sc and {**sc, "assumed": {**sc["assumed"], **settings}})]
    print(f"{len(done)} clips: " + ", ".join(f"{k}={json.dumps(v)}" for k, v in settings.items()))
    for c in set(clips) - set(done):
        print(f"{library.name_of(c)}: no sidecar yet; run python -m footage first")
