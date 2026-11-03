"""Every Library clip graded on its own: one timeline and one master per clip, in Graded/DAY/.

Each clip's timeline is the whole take with its sound, cut in and out with no fades, printed in the house look (or
--look) through footage.render. The timeline records the stamp of what its master was rendered from: the clip's bytes,
what the grade reads from the sidecar (assumed, measured, focus), the clip's person, and the look's file. A master is
current while that stamp still holds, and a current master is skipped, so a run that stops resumes where it left off.
A clip whose sidecar isn't ready (missing or out-of-date sections, a RAW clip not developed yet) waits for the next run.
Newest days go first.

python -m footage.graded [--look NAME] [--out DIR]
"""
import argparse
import hashlib
import json
import subprocess
from fractions import Fraction
from functools import cache
from pathlib import Path

import opentimelineio as otio

from . import grade, idle, library, probe, render

OUT = Path.home() / "Videos/Graded"


@cache
def look_id(look: grade.Look) -> str:
    return hashlib.sha1((grade.LOOKS / f"{look.name}.json").read_bytes() + look.lut.read_bytes()).hexdigest()


def stamp(sc: dict, look: grade.Look) -> str:
    made_from = {"sha256": sc["facts"]["sha256"], **{k: sc.get(k) for k in ("assumed", "measured", "focus", "person")},
                 "look": look_id(look)}
    return hashlib.sha1(json.dumps(made_from, sort_keys=True, default=str).encode()).hexdigest()


def frames(clip: Path) -> int:
    """How many video frames the file holds: its index's count, or the packets counted where it keeps none (fragmented MP4)."""
    ask = lambda *how: subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", *how, "-of", "csv=p=0", str(clip)],
                                      capture_output=True, text=True, check=True).stdout.strip().strip(",")
    count = ask("-show_entries", "stream=nb_frames")
    return int(count if count.isdigit() else ask("-count_packets", "-show_entries", "stream=nb_read_packets"))


def timeline(clip: Path, sc: dict, look: grade.Look) -> otio.schema.Timeline:
    """The whole take: every video frame the file holds, and its sound if it has any."""
    rate = float(Fraction(sc["facts"]["fps"]))
    whole = otio.opentime.TimeRange(otio.opentime.RationalTime(0, rate), otio.opentime.RationalTime(frames(clip), rate))
    take = lambda: otio.schema.Clip(name=clip.name, media_reference=otio.schema.ExternalReference(target_url=str(clip)),
                                    source_range=whole)
    t = otio.schema.Timeline(name=clip.name, metadata={"footage": {"look": look.name, "fades": [0, 0], "stamp": None}})
    t.tracks.append(otio.schema.Track(children=[take()], kind=otio.schema.TrackKind.Video))
    if any(s["codec_type"] == "audio" for s in probe.ffprobe(clip)["streams"]):
        sound = take()
        sound.metadata["footage"] = {"lufs": -21}
        t.tracks.append(otio.schema.Track(children=[sound], kind=otio.schema.TrackKind.Audio))
    return t


def stamped(edit: Path) -> str | None:
    t = otio.adapters.read_from_file(str(edit))  # held: metadata read from a temporary timeline is freed under it
    return t.metadata["footage"].get("stamp")


def grade_all(lib: Path, out: Path, look: grade.Look) -> None:
    clips = sorted(library.clips(lib), key=lambda c: (c.parent.name, c.name), reverse=True)
    counts = {"current": 0, "rendered": 0, "waiting": 0, "failed": 0}
    for i, clip in enumerate(clips, 1):
        edit = out / clip.parent.name / f"{clip.name}.otio"  # the full name: A.MP4 and A.CRM may share a day
        master = edit.with_name(f"{edit.stem} - {look.name}.mp4")
        try:
            sc = render.read(clip)
        except (SystemExit, ValueError) as e:
            counts["waiting"] += 1
            print(f"waiting {i}/{len(clips)} {library.name_of(clip)}: {e}", flush=True)
            continue
        made_from = stamp(sc, look)
        if master.exists() and edit.exists() and stamped(edit) == made_from:
            counts["current"] += 1
            continue
        print(f"rendering {i}/{len(clips)} {library.name_of(clip)}", flush=True)
        try:
            edit.parent.mkdir(parents=True, exist_ok=True)
            t = timeline(clip, sc, look)
            otio.adapters.write_to_file(t, str(edit))
            render.render(edit, look.name)
        except Exception as e:  # the master stays out of date and the next run retries it
            counts["failed"] += 1
            print(f"failed {library.name_of(clip)}: {e!r}"[:300], flush=True)
            continue
        t.metadata["footage"]["stamp"] = made_from
        otio.adapters.write_to_file(t, str(edit))
        counts["rendered"] += 1
    print("; ".join(f"{k}: {v}" for k, v in counts.items()), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="footage.graded")
    ap.add_argument("--look", default=grade.DEFAULT)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--library", type=Path, default=Path.home() / "Videos/Library")
    a = ap.parse_args()
    idle()
    grade_all(a.library, a.out, grade.look(a.look))
