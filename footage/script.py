"""Cut a clip by its words: list its sentences, keep some, and get a timeline of just those seconds.

A sentence ends where its punctuation does, where the voice changes, or where speech pauses. Keeping sentences
1, 3-5 writes an OTIO timeline whose clips are exactly those stretches of the one recording, picture and sound
together, the sound marked dialogue (-15 LUFS in the render). What is not kept is not in the edit: fillers, repeats
and dead air go by deleting their sentences here rather than by hunting timecodes. Render it like any edit:
python -m footage.render CLIP-script.otio.

python -m footage.script CLIP.MP4                      # the numbered sentences
python -m footage.script CLIP.MP4 --keep 1,3-5         # CLIP-script.otio beside the clip's day folder output
"""
import argparse
from fractions import Fraction
from pathlib import Path

import opentimelineio as otio

from . import idle, passes, sidecar

PAUSE = 0.8  # seconds of no words that also ends a sentence
PAD = (0.05, 0.15)  # kept around the words: a breath in, the tail of the last sound out
JOIN = 0.3  # kept stretches this close become one, so a kept pause makes no jump


def sentences(words: list[dict]) -> list[dict]:
    """The transcript's words grouped into sentences, each with its seconds, voice and text."""
    out, run = [], []
    for i, w in enumerate(words):
        run.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None or w["text"].endswith((".", "!", "?")) or nxt.get("voice") != w.get("voice") \
                or nxt["start"] - w["end"] >= PAUSE:
            out.append({"start": run[0]["start"], "end": run[-1]["end"], "voice": w.get("voice"),
                        "text": " ".join(x["text"] for x in run)})
            run = []
    return out


def ranges(kept: list[dict], duration: float) -> list[tuple[float, float]]:
    """The seconds the kept sentences occupy, padded a breath either side and joined where they nearly touch."""
    spans = sorted((max(s["start"] - PAD[0], 0.0), min(s["end"] + PAD[1], duration)) for s in kept)
    joined: list[list[float]] = []
    for a, b in spans:
        if joined and a - joined[-1][1] < JOIN:
            joined[-1][1] = max(joined[-1][1], b)
        else:
            joined.append([a, b])
    return [(a, b) for a, b in joined]


def timeline(clip: Path, sc: dict, spans: list[tuple[float, float]]) -> otio.schema.Timeline:
    """One recording cut to spans: a video and an audio clip per span, the sound marked dialogue."""
    rate = float(Fraction(sc["facts"]["fps"]))
    at = lambda a, b: otio.opentime.TimeRange(otio.opentime.RationalTime(round(a * rate), rate),
                                              otio.opentime.RationalTime(max(1, round((b - a) * rate)), rate))
    take = lambda a, b: otio.schema.Clip(name=clip.name, source_range=at(a, b),
                                         media_reference=otio.schema.ExternalReference(target_url=str(clip)))
    t = otio.schema.Timeline(name=f"{clip.stem} script", metadata={"footage": {"fades": [0, 0]}})
    t.tracks.append(otio.schema.Track(children=[take(a, b) for a, b in spans], kind=otio.schema.TrackKind.Video))
    sound = []
    for a, b in spans:
        c = take(a, b)
        c.metadata["footage"] = {"lufs": -15}
        sound.append(c)
    t.tracks.append(otio.schema.Track(children=sound, kind=otio.schema.TrackKind.Audio))
    return t


def pick(text: str, n: int) -> list[int]:
    """A --keep list like 1,3-5 as sentence indexes, checked against how many there are."""
    out = []
    for part in text.split(","):
        a, _, b = part.partition("-")
        out += range(int(a), int(b or a) + 1)
    if any(not 1 <= i <= n for i in out):
        raise SystemExit(f"--keep names a sentence outside 1..{n}")
    return sorted(set(out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="footage.script")
    ap.add_argument("clip", type=Path)
    ap.add_argument("--keep", help="sentences to keep, like 1,3-5 (default: list them)")
    ap.add_argument("--out", type=Path, help="the .otio to write (default: CLIP-script.otio beside this command's folder)")
    a = ap.parse_args()
    idle()
    sc = sidecar.read(a.clip)
    if sc is None:
        raise SystemExit(f"{a.clip.name} has no sidecar: run python -m footage first")
    sc, stale = passes.fresh(a.clip, sc)
    if "transcript" not in sc:
        raise SystemExit(f"{a.clip.name}: transcript missing or out of date: run python -m footage first")
    said = sentences(sc["transcript"].get("words", []))
    if not said:
        raise SystemExit(f"{a.clip.name}: no speech transcribed")
    if not a.keep:
        for i, s in enumerate(said, 1):
            print(f"{i:3} {s['start']:7.2f}-{s['end']:<7.2f} {s['text']}")
    else:
        kept = [said[i - 1] for i in pick(a.keep, len(said))]
        spans = ranges(kept, sc["facts"]["duration"])
        out = a.out or Path(f"{a.clip.stem}-script.otio")
        otio.adapters.write_to_file(timeline(a.clip, sc, spans), str(out))
        print(f"{out}: {len(spans)} stretches, {sum(b - a for a, b in spans):.1f}s of {sc['facts']['duration']:.1f}s kept")
