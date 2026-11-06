"""python -m footage.transcribe FILE: any recording's speaker-labelled transcript, as word JSON, Markdown, SRT and VTT.

    python -m footage.transcribe FILE [--speakers N] [--names "Ana,Ben"] [--out DIR] [--library DIR]
    python -m footage.transcribe DIR/NAME.json --names "Ana,Ben,Ana"    # rename voices and re-render, no re-run

NAME.json is the transcript, the same shape as a clip's transcript section, with the source, its duration and the
voices' names; the other three files are rendered from it, so a hand fix to a word's speaker or a renamed voice is one
re-render away, and voices given one name render as one person. NAME is the source's whole file name plus
".transcript", and a run writes over no transcript but the one it re-renders.

NAME.json also holds each voice's print. A voice that matches a known person (people.names) is given their name, and
every named voice, matched or named by --names, is recorded under that person in the Library's people.json, so a
renamed voice's print moves with its name. Prints are biometric: keep transcripts and people.json out of git.
"""
import argparse
import json
from pathlib import Path

from .. import idle, people
from .formats import name, render
from .hear import RATE, audio, hear, identity


def transcribe(media: Path, speakers: int | None, lib: Path) -> dict:
    a = audio(media)
    doc = hear(a, speakers)
    found = people.names([v["print"] for v in doc["voices"]], people.known(lib / "people.json"), people.at(media, lib))
    return {"source": str(media.resolve()), "duration": round(a.size / RATE, 2), "id": identity({}), **doc,
            "speakers": [n or f"Speaker {i + 1}" for i, n in enumerate(found)]}


def main() -> None:
    ap = argparse.ArgumentParser(prog="footage.transcribe", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path, help="any audio or video file ffmpeg reads, or a .json this wrote")
    ap.add_argument("--speakers", type=int, help="how many voices, when known: clustering is much better")
    ap.add_argument("--names", default="", help="names in the order the voices first speak")
    ap.add_argument("--out", type=Path, help="output folder; default: beside FILE")
    ap.add_argument("--library", type=Path, default=Path.home() / "Videos/Library", help="whose people.json knows the voices")
    a = ap.parse_args()
    idle()
    out = a.out or a.file.resolve().parent
    rerender = a.file.suffix == ".json"
    doc = json.loads(a.file.read_text()) if rerender else None
    # The one transcript a run may write over is the one it re-renders: any other may hold hand fixes.
    dest = Path(f"{name(doc['source'] if rerender else str(a.file.resolve()), out)}.json")
    if dest.exists() and not (rerender and dest.resolve() == a.file.resolve()):
        raise SystemExit(f"{dest} exists: re-render from it, or delete it to transcribe again")
    doc = doc or transcribe(a.file, a.speakers, a.library)
    for i, given in enumerate(a.names.split(",")[:len(doc["speakers"])]):
        doc["speakers"][i] = given.strip() or doc["speakers"][i]
    if "voices" in doc:  # a transcript from before voices had prints has nothing to record, or to take away
        named: dict = {}
        for v in doc["voices"]:  # a voice still called by its number is nobody yet
            if doc["speakers"][v["voice"]] != f"Speaker {v['voice'] + 1}":
                named.setdefault(doc["speakers"][v["voice"]], []).append({**v, "by": "transcript"})
        source = people.at(Path(doc["source"]), a.library)
        people.update(a.library, lambda entries: people.heard(entries, source, named))
    out.mkdir(parents=True, exist_ok=True)
    print(f"{render(doc, out)}.{{json,md,srt,vtt}}: {len(doc['words'])} words, voices: {', '.join(dict.fromkeys(doc['speakers']))}")


if __name__ == "__main__":
    main()
