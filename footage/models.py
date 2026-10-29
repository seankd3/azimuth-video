"""Where the toolkit's local model files live, and what identifies a model: its files' names and sizes.

A new model arrives under a new name, and a replaced or damaged file almost never keeps its size. Sizes, not hashes,
so checking whether a section is current never reads gigabytes of weights.
"""
from pathlib import Path

FOLDER = Path.home() / ".local/share/footage/models"


def identity(*paths: Path) -> dict:
    """Name and size of each model file; a folder stands for every file in it."""
    out = {}
    for p in paths:
        for f in [p] if p.is_file() else sorted(p.rglob("*")):
            if f.is_file():
                out[str(f.relative_to(p.parent))] = f.stat().st_size
    return out
