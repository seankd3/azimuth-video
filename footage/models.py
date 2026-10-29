"""Where the toolkit's local models live, and what identifies one: its files' names and sizes.

FOLDER holds read-only snapshots, and nothing replaces a file in it: a new model or version is published under a new
name, after `chmod u+w` on the folder. So the files a pass is identified by are the files it loads, and sizes, not
hashes, are enough; checking whether a section is current never reads gigabytes of weights.
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
