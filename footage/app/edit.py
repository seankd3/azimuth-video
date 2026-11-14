"""An edit file and its history: the one door every change to an edit goes through.

The edit is the OTIO timeline the renderer reads. The app changes only video track 1 (the picture) and the timeline's
settings, and keeps everything else as written (sound tracks, title cards, an agent's metadata). Every change is an
action: a function that changes a copy of the timeline. The door makes the copy valid (each shot inside its source and
at least a frame long, each framing through view.frame), appends it to the history and writes the file, so there is no
unsaved state. A write from outside (an agent) is read in as one more entry, so undo takes it back too.
"""
import os
from fractions import Fraction
from pathlib import Path

import opentimelineio as otio

from .. import sidecar, view

ASPECTS = (("2.39", 2.39), ("16:9", 16 / 9), ("9:16", 9 / 16), ("1:1", 1.0), ("4:5", 0.8), ("Full", "full"))


def picture(t: otio.schema.Timeline) -> otio.schema.Track:
    return t.video_tracks()[0]


def media(clip: otio.schema.Clip) -> Path | None:
    ref = clip.media_reference
    return Path(ref.target_url) if isinstance(ref, otio.schema.ExternalReference) else None


def facts(path: Path) -> dict:
    """What the door and the view read of a clip: its sidecar, whose facts and assumptions hold its geometry."""
    sc = sidecar.read(path)
    if sc is None:
        raise ValueError(f"{path.name} has no sidecar: file it into the Library first")
    return sc


def aspect(t: otio.schema.Timeline) -> float:
    """The edit's aspect as a number. "full" in an edit with no filmed shot yet is the default."""
    value = t.metadata.get("footage", {}).get("aspect", view.ASPECT)
    first = next((p for c in picture(t).find_clips(shallow_search=True) if (p := media(c))), None)
    return view.aspect(value, [facts(first)]) if first else float(view.ASPECT if value == "full" else value)


def valid(t: otio.schema.Timeline) -> None:
    """Make every shot valid in place: inside its source, at least one frame, and its framing through view.frame."""
    a = aspect(t)
    for clip in picture(t).find_clips(shallow_search=True):
        path = media(clip)
        if path is None:
            continue
        sc = facts(path)
        rate = float(Fraction(sc["facts"]["fps"]))
        length, frame = sc["facts"]["duration"], 1 / rate
        r = clip.source_range
        start = min(max(r.start_time.to_seconds(), 0), length - frame)
        end = min(max(start + r.duration.to_seconds(), start + frame), length)
        clip.source_range = otio.opentime.TimeRange(otio.opentime.from_seconds(start, rate).round(),
                                                    otio.opentime.from_seconds(end - start, rate).round())
        meta = clip.metadata.setdefault("footage", {})
        if "framing" in meta:
            meta["framing"] = view.frame(sc, dict(meta["framing"]), a)


def shot(path: Path, start: float = 0, duration: float | None = None) -> otio.schema.Clip:
    sc = facts(path)
    rate = float(Fraction(sc["facts"]["fps"]))
    d = sc["facts"]["duration"] - start if duration is None else duration
    return otio.schema.Clip(name=path.stem, media_reference=otio.schema.ExternalReference(target_url=str(path)),
                            source_range=otio.opentime.TimeRange(otio.opentime.from_seconds(start, rate),
                                                                 otio.opentime.from_seconds(d, rate)))


def new(clips: list[Path]) -> otio.schema.Timeline:
    t = otio.schema.Timeline(name=clips[0].stem)
    t.tracks.append(otio.schema.Track(name="Picture", kind=otio.schema.TrackKind.Video))
    for c in clips:
        picture(t).append(shot(c))
    return t


# The actions. Each changes the timeline in place; the door hands it a copy.

def split(t, i: int, at: float) -> None:
    """Split shot i `at` seconds into it."""
    track, clip = picture(t), picture(t)[i]
    r, rate = clip.source_range, clip.source_range.duration.rate
    cut = otio.opentime.from_seconds(at, rate).round()
    second = clip.clone()
    clip.source_range = otio.opentime.TimeRange(r.start_time, cut)
    second.source_range = otio.opentime.TimeRange(r.start_time + cut, r.duration - cut)
    track.insert(i + 1, second)


def trim(t, i: int, start: float, end: float) -> None:
    """Shot i shows its source from `start` to `end` seconds."""
    clip = picture(t)[i]
    rate = clip.source_range.duration.rate
    clip.source_range = otio.opentime.TimeRange(otio.opentime.from_seconds(start, rate).round(),
                                                otio.opentime.from_seconds(end - start, rate).round())


def move(t, i: int, to: int) -> None:
    track = picture(t)
    clip = track[i]
    del track[i]
    track.insert(to, clip)


def remove(t, i: int) -> None:
    del picture(t)[i]


def add(t, at: int, path: str, start: float = 0, duration: float | None = None) -> None:
    picture(t).insert(at, shot(Path(path), start, duration))


def frame(t, i: int, framing: dict) -> None:
    picture(t)[i].metadata.setdefault("footage", {})["framing"] = framing


def setting(t, key: str, value) -> None:
    t.metadata.setdefault("footage", {})[key] = value


def text(t: otio.schema.Timeline) -> str:
    """An edit as the history holds it: the JSON a write and a read back give. OTIO's JSON doesn't carry every float
    exactly, so this is the form the file shows, and equal edits compare equal."""
    return otio.adapters.read_from_string(t.to_json_string(), "otio_json").to_json_string()


class Edit:
    """An edit file, its history (the timeline as JSON, oldest first) and the position in it."""

    def __init__(self, path: Path, timeline: otio.schema.Timeline | None = None):
        self.path = path
        if timeline is not None:
            valid(timeline)
            self.history, self.at = [text(timeline)], 0
            self._write()
        else:
            self.history, self.at = [self._read()], 0
        self._timeline = None

    @property
    def timeline(self) -> otio.schema.Timeline:
        """The current edit. Callers read it; only `do` changes it."""
        if self._timeline is None:
            self._timeline = otio.adapters.read_from_string(self.history[self.at], "otio_json")
        return self._timeline

    def do(self, action, *args) -> bool:
        """Apply an action through the door. False when it changed nothing."""
        t = otio.adapters.read_from_string(self.history[self.at], "otio_json")
        action(t, *args)
        valid(t)
        return self._push(text(t))

    def undo(self) -> bool:
        return self._go(self.at - 1)

    def redo(self) -> bool:
        return self._go(self.at + 1)

    def outside(self) -> bool:
        """Read the file in as one more entry if something else wrote it since the door last did."""
        try:
            text = self._read()
        except (OSError, ValueError):
            return False  # mid-write, or gone: the next change notice reads it
        return text != self.history[self.at] and self._push(text, write=False)

    def _push(self, text: str, write: bool = True) -> bool:
        if text == self.history[self.at]:
            return False
        self.history, self.at, self._timeline = self.history[:self.at + 1] + [text], self.at + 1, None
        if write:
            self._write()
        return True

    def _go(self, at: int) -> bool:
        if not 0 <= at < len(self.history):
            return False
        self.at, self._timeline = at, None
        self._write()
        return True

    def _read(self) -> str:
        return text(otio.adapters.read_from_file(str(self.path)))

    def _write(self) -> None:
        part = self.path.with_name(f".{self.path.name}.part")
        part.write_text(self.history[self.at])
        os.replace(part, self.path)  # whole or not at all: a reader never sees half an edit
