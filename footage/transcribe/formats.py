"""A transcript read as people read it: turns (one voice speaking, paragraph by paragraph), and the four files a
recording's transcript is kept as: NAME.json (the transcript itself) and Markdown, SRT and VTT rendered from it."""
import json
from pathlib import Path

PARAGRAPH_GAP = 2.0  # seconds of silence that start a new paragraph for the same voice
CUE_CHARS, CUE_LINE, CUE_SECONDS, CUE_GAP = 84, 42, 6.0, 0.7  # subtitle cues: two lines of 42, at most 6 s


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


def turns(words: list, names: list | None = None) -> list[dict]:
    """Paragraphs: a new one when another person speaks or after PARAGRAPH_GAP of silence. Voices given one name are
    one person; without names, each voice is its own."""
    who = (lambda w: names[w["speaker"]]) if names else (lambda w: w["speaker"])
    return [{"speaker": g[0]["speaker"], "start": g[0]["start"], "end": g[-1]["end"], "text": text(g)}
            for g in grouped(words, lambda g, w: who(w) != who(g[-1]) or w["start"] - g[-1]["end"] > PARAGRAPH_GAP)]


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
    """NAME: the source's whole file name plus ".transcript", so outputs never meet a clip's sidecar or another file."""
    return out / f"{Path(source).name}.transcript"


def render(doc: dict, out: Path) -> Path:
    words, names = doc["words"], doc["speakers"]
    people = list(dict.fromkeys(names))
    stem = name(doc["source"], out)
    doc["turns"] = turns(words, names)
    Path(f"{stem}.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")

    md = [f"# {Path(doc['source']).name}", "", f"{clock(doc['duration'], hours=False)}, voices: {', '.join(people)}", ""]
    for t in doc["turns"]:
        md += [f"**{names[t['speaker']]}** {clock(t['start'], hours=False)}", "", t["text"], ""]
    Path(f"{stem}.md").write_text("\n".join(md))

    # A cue lasts as long as its words, so it is never empty; two words heard on one frame may overlap it with the next.
    cues = list(grouped(words, lambda g, w: (
        names[w["speaker"]] != names[g[-1]["speaker"]] or w["start"] - g[-1]["end"] > CUE_GAP
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
