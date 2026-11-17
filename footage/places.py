"""Where the toolkit's files live, named once. Footage and all that is made from it live under ~/Videos; the toolkit's
own files (models, programs and caches) under ~/.local/share/footage. A machine with a drive for video mounts it at
those two folders, and nothing the toolkit writes lands anywhere else.

SCRATCH is for work in progress that can be deleted: test renders, frames, logs. Each job takes its own folder,
"<date> <topic>".
"""
from pathlib import Path

VIDEOS = Path.home() / "Videos"
INGEST, LIBRARY, EDITS, GRADED, SCRATCH = (VIDEOS / f for f in ("Ingest", "Library", "Edits", "Graded", "Scratch"))

DATA = Path.home() / ".local/share/footage"
MODELS, VENDOR, CACHE = DATA / "models", DATA / "vendor", DATA / "cache"

BIN = Path.home() / ".local/bin"
