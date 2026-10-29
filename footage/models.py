"""Where the toolkit's local model files live, and what identifies a model: its files' names and sizes.

Sizes, not hashes, so checking whether a section is current never reads gigabytes of weights. A new model must arrive
under a new name; a file replaced in place by one of the same size goes unnoticed.
"""
from functools import cache
from pathlib import Path

FOLDER = Path.home() / ".local/share/footage/models"


@cache
def identity(*paths: Path) -> dict:
    """Name and size of each model file; a folder stands for every file in it. Read once per process, as the models
    themselves are loaded once, so a run stamps the files it loaded."""
    out = {}
    for p in paths:
        for f in [p] if p.is_file() else sorted(p.rglob("*")):
            if f.is_file():
                out[str(f.relative_to(p.parent))] = f.stat().st_size
    return out
