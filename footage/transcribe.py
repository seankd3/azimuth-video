"""python -m footage.transcribe FILE: any recording's speaker-labelled transcript, as word JSON, Markdown, SRT and VTT.

    python -m footage.transcribe FILE [--speakers N] [--names "Sean,Paul"] [--out DIR] [--library DIR]
    python -m footage.transcribe DIR/NAME.json --names "Sean,Paul,Sean"    # rename voices and re-render, no re-run

The words come from listen.hear, the same function as a clip's transcript section. NAME.json holds every word (text,
start, end, confidence, speaker) and the speakers' names; the other three files are rendered from it, so a hand fix
to a word's speaker or a renamed voice is one re-render away, and voices given one name render as one person. NAME is
the source's whole file name plus ".transcript", so outputs never meet a clip's sidecar or another file, and a run
writes over no transcript but the one it re-renders.

NAME.json also holds each voice's print. A voice that matches a known person (people.names) is given their name, and
every named voice, matched or named by --names, is recorded under that person in the Library's people.json, so a
renamed voice's print moves with its name. Prints are biometric: keep transcripts and people.json out of git.
"""
import argparse
import json
from pathlib import Path

from . import idle, listen, people

PARAGRAPH_GAP = 2.0  # seconds of silence that start a new paragraph for the same voice
CUE_CHARS, CUE_LINE, CUE_SECONDS, CUE_GAP = 84, 42, 6.0, 0.7  # subtitle cues: two lines of 42, at most 6 s


def transcribe(media: Path, speakers: int | None, lib: Path) -> dict:
    a = listen.audio(media)
    lines, prints = listen.hear(a, speakers) if a.size else ([], {})
    words = [w for line in lines for w in line["words"]]
    order = list(dict.fromkeys(w["speaker"] for w in words))
    for w in words:  # voices numbered by first appearance, so --names goes in the order people speak
        w["speaker"] = order.index(w["speaker"])
    voices = []
    for i, k in enumerate(order):
        said = [w for w in words if w["speaker"] == i]
        voices.append({"voice": i, "start": said[0]["start"], "end": said[-1]["end"],
                       "seconds": round(sum(w["end"] - w["start"] for w in said), 1),
                       "print": [round(float(x), 4) for x in prints[k]]})
    found = people.names([v["print"] for v in voices], people.known(lib / "people.json"), people.at(media, lib))
    return {"source": str(media.resolve()), "duration": round(a.size / listen.RATE, 2), "listen": listen.identity({}),
            "speakers": [n or f"Speaker {i + 1}" for i, n in enumerate(found)], "voices": voices, "words": words}


def grouped(words, breaks):
    group = []
    for w in words:
        if group and breaks(group, w):
            yield group
            group = []
        group.append(w)
    if group:
        yield group


def text(words) -> str:
    return " ".join(w["text"] for w in words)


def wrap(line: str) -> str:
    if len(line) <= CUE_LINE:
        return line
    cut = min((i for i, c in enumerate(line) if c == " "), key=lambda i: abs(i - len(line) / 2), default=None)
    return line if cut is None else line[:cut] + "\n" + line[cut + 1:]


def clock(t: float, sep: str = ".", hours: bool = True) -> str:
    m, ms = divmod(round(t * 1000), 60000)
    h, m = divmod(m, 60)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}" if hours else f"{h * 60 + m:02d}:{s:02d}"


def name(source: str, out: Path) -> Path:
    return out / f"{Path(source).name}.transcript"


def render(doc: dict, out: Path) -> Path:
    words, names = doc["words"], doc["speakers"]
    people = list(dict.fromkeys(names))
    stem = name(doc["source"], out)
    other = lambda g, w: names[w["speaker"]] != names[g[-1]["speaker"]]  # voices given one name are one person
    turns = list(grouped(words, lambda g, w: other(g, w) or w["start"] - g[-1]["end"] > PARAGRAPH_GAP))
    doc["turns"] = [{"speaker": g[0]["speaker"], "start": g[0]["start"], "end": g[-1]["end"], "text": text(g)} for g in turns]
    Path(f"{stem}.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")

    md = [f"# {Path(doc['source']).name}", "", f"{clock(doc['duration'], hours=False)}, voices: {', '.join(people)}", ""]
    for t in doc["turns"]:
        md += [f"**{names[t['speaker']]}** {clock(t['start'], hours=False)}", "", t["text"], ""]
    Path(f"{stem}.md").write_text("\n".join(md))

    # A cue lasts as long as its words, so it is never empty; two words heard on one frame may overlap it with the next.
    cues = list(grouped(words, lambda g, w: (
        other(g, w) or w["start"] - g[-1]["end"] > CUE_GAP
        or len(text(g + [w])) > CUE_CHARS or w["end"] - g[0]["start"] > CUE_SECONDS
        or (g[-1]["text"][-1:] in ".?!" and len(text(g)) > CUE_LINE / 2))))
    srt, vtt = [], ["WEBVTT", ""]
    for i, g in enumerate(cues):
        start, end = g[0]["start"], g[-1]["end"]
        line, who = wrap(text(g)), names[g[0]["speaker"]]
        srt += [str(i + 1), f"{clock(start, ',')} --> {clock(end, ',')}", f"{who}: {line}" if len(people) > 1 else line, ""]
        vtt += [f"{clock(start)} --> {clock(end)}", f"<v {who}>{line}" if len(people) > 1 else line, ""]
    Path(f"{stem}.srt").write_text("\n".join(srt))
    Path(f"{stem}.vtt").write_text("\n".join(vtt))
    return stem


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
