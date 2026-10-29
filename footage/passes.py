"""The passes that fill a clip's sidecar, and the one rule for whether what a pass wrote is still current.

Each pass owns one section and stamps it with `id`: its module's `identity`, everything the output depends on (code
versions, picture geometry, colour decoding, models, settings). A section is current while the clip's bytes are
unchanged and its id is still what the pass would stamp now. Changing any of those makes the section stale everywhere
at once: python -m footage redoes it, render stops on it, and find leaves it out.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import describe, focus, listen, measure, probe, steady


@dataclass
class Pass:
    section: str
    run: Callable[[Path, dict], dict]
    identity: Callable[[dict], dict]
    workers: int
    available: Callable[[], bool] = lambda: True


PASSES = [
    # Two requests keep the model busy while the next frames are cut.
    Pass("description", describe.describe, describe.identity, 2, describe.available),
    Pass("transcript", listen.listen, listen.identity, 1),
    Pass("measured", measure.measure, measure.identity, 4),
    # These two read every frame on the GPU decoder.
    Pass("focus", focus.focus, focus.identity, 2),
    Pass("shake", steady.shake, steady.identity, 2),
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
