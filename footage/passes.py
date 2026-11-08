"""The passes that fill a clip's sidecar, and the one rule for whether what a pass wrote is still current.

Each pass owns one section and stamps it with `id`: its module's `identity`, everything the output depends on (code
versions, picture geometry, colour decoding, models, settings). A section is current while the clip's bytes are
unchanged and its id is still what the pass would stamp now. Changing any of those makes the section stale everywhere
at once: python -m footage redoes it, render stops on it, and find leaves it out.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import describe, embed, focus, measure, probe, takes, transcribe


@dataclass
class Pass:
    section: str
    run: Callable[[Path, dict], dict | None]  # None: nothing to store yet
    identity: Callable[[dict], dict]
    workers: int


PASSES = [
    # Writes questions, and takes the answers its describer left; see describe.py.
    Pass("description", describe.describe, describe.identity, 2),
    Pass("transcript", transcribe.clip, transcribe.identity, 1),
    Pass("measured", measure.measure, measure.identity, 4),
    # Reads every frame on the GPU decoder, one clip at a time: its frame buffers count as system memory on a
    # shared-memory GPU, and two clips at once reached 15 GB.
    Pass("focus", focus.focus, focus.identity, 1),
    # One clip at a time: the model holds the GPU, and each clip's frames are cut 8 at once.
    Pass("embedding", embed.embed, embed.identity, 1),
    # Three frames' features, for telling which clips are takes of one angle (takes.py).
    Pass("angle", takes.angle, takes.identity, 2),
]
OWNER = {p.section: p for p in PASSES}


def current(sc: dict, section: str) -> bool:
    """Whether the section exists and was made from what its pass would read now. The clip's bytes are checked apart."""
    return section in sc and sc[section].get("id") == OWNER[section].identity(sc)


def fresh(clip: Path, sc: dict) -> tuple[dict, list[str]]:
    """The sidecar as a reader may use it: without the sections that are out of date, and their names. When the clip's
    bytes no longer match its facts, every section is out of date."""
    same = probe.unchanged(clip, sc["facts"])
    stale = [s for s in OWNER if s in sc and not (same and current(sc, s))]
    return {k: v for k, v in sc.items() if k not in stale}, stale
