"""Who appears across the Library: faces grouped into people by fingerprint, voices known by name, and what you've
said about each.

`people.json` beside the day folders lists each person: an id, the clips their face is in, a face fingerprint, their
`voices`, and two things only you fill in: a `name`, and `skin_stops`, where their lit cheek should sit (stops above
18% grey). Skin level is a judgement, not a measurement: no frame can tell darker skin from underexposure, so the
machine never guesses it. Entries that share a name are one person. Rebuilding keeps ids, names, skin levels and
voices, and a person you named, gave a skin level or whose voice is known stays listed while none of their clips is
measured, so what you wrote is never lost. A clip's subject is looked up here when a reader asks (people.of), so an
edited name or skin level holds at once.

Every other voice with at least HEARD seconds of speech is grouped across the Library with the voices it sounds
like, under one id, so a voice has one label in every clip: its name once you give it one, its id until then.

A voice is known once it has a name: naming a voice in a transcript (python -m footage.transcribe NAME.json --names)
records its print, with the file and time it came from, under that person. A new transcript, and each clip's
transcript at every build, gives a voice the name of the known person it matches (VOICE), and that print is recorded
too, so the registry learns. A print records who decided it: "transcript" (named or accepted in a transcript) or
"build" (matched by a build). A build never changes the prints of a recording named in a transcript. Prints are
biometric: people.json stays in the Library, never in git.
"""
import fcntl
import json
import os
from functools import cache
from pathlib import Path

import numpy as np

from . import face, library, sidecar
from .passes import fresh

ACROSS = 0.95  # stricter than face.SAME across clips, comparing every member: splitting one person is harmless, merging two is not
VOICE = 0.7  # TitaNet-large cosine at which two files' voices are one person: across 18 named voices in 9 recordings
#             one person scored 0.72 to 0.90, and two different people at most 0.54
HEARD = 4.0  # seconds of speech a voice needs before it is grouped with voices in other files


def unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def tracks(measured: dict) -> list[dict]:
    """The distinct faces in one clip: its detections grouped by fingerprint."""
    out = []
    for d in sorted(measured.get("faces", []), key=lambda d: -d["height"]):
        p = unit(d["print"])
        best = max(out, key=lambda t: float(t["print"] @ p), default=None)
        if best is not None and float(best["print"] @ p) >= face.SAME:
            best["members"].append(d)
            best["print"] = unit(np.mean([unit(m["print"]) for m in best["members"]], axis=0))
        else:
            out.append({"print": p, "members": [d]})
    for t in out:
        t["key_stops"] = float(np.median([m["key_stops"] for m in t["members"]]))
        t["height"] = max(m["height"] for m in t["members"])
    return out


def update(lib: Path, change) -> list:
    """Change people.json as one step: `change` gets its entries and returns the new ones. Every writer goes through
    here, under a lock on the Library folder, so a build and a transcript naming a voice never lose each other's edit."""
    lib.mkdir(parents=True, exist_ok=True)
    path = lib / "people.json"
    fd = os.open(lib, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        entries = change(json.loads(path.read_text())["people"] if path.exists() else [])
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({"people": entries}, indent=1))
        os.rename(tmp, path)
        return entries
    finally:
        os.close(fd)


def build(lib: Path, report: list) -> None:
    clips = {}
    for clip in library.clips(lib):
        try:
            sc = sidecar.read(clip)
        except ValueError:
            continue
        if sc:
            clips[clip] = fresh(clip, sc)[0]
    found = [(clip, t) for clip, sc in clips.items() if "measured" in sc for t in tracks(sc["measured"])]
    people = []
    if len(found) > 1:
        from scipy.cluster.hierarchy import fcluster, linkage
        groups = fcluster(linkage(np.array([t["print"] for _, t in found]), method="complete", metric="cosine"),
                          t=1 - ACROSS, criterion="distance")
        for g in sorted(set(groups)):
            members = [found[i] for i in np.nonzero(groups == g)[0]]
            people.append({"print": unit(np.mean([t["print"] for _, t in members], axis=0)), "tracks": members})
    elif found:
        people = [{"print": found[0][1]["print"], "tracks": found}]

    def change(known: list) -> list:
        # Carry ids, names and voices over from the last build; new people get the next free id.
        faces = [k for k in known if k.get("print")]
        used = set()
        for p in people:
            match = max((k for k in faces if k["id"] not in used), key=lambda k: float(unit(k["print"]) @ p["print"]), default=None)
            if match is not None and float(unit(match["print"]) @ p["print"]) >= face.SAME:
                p["id"], p["name"], p["skin_stops"] = match["id"], match.get("name"), match.get("skin_stops")
                p["voices"] = match.get("voices", [])
            else:
                taken = {k["id"] for k in known} | {q.get("id") for q in people}
                p["id"], p["name"], p["skin_stops"], p["voices"] = next(f"p{i:02d}" for i in range(1, 999) if f"p{i:02d}" not in taken), None, None, []
            used.add(p["id"])
            p["clips"] = sorted({library.name_of(clip) for clip, _ in p["tracks"]})
        for p in people:  # a skin level given to one entry of a named person holds for all of them
            p["skin_stops"] = next((q["skin_stops"] for q in people if q["skin_stops"] is not None and p["name"]
                                    and q["name"] == p["name"]), p["skin_stops"])
        entries = [{"id": p["id"], "name": p["name"], "skin_stops": p["skin_stops"], "clips": p["clips"],
                    "print": [round(float(v), 3) for v in p["print"]], "voices": p["voices"]} for p in people]
        entries += [{**k, "clips": []} for k in known if k["id"] not in used
                    and (k.get("name") or k.get("skin_stops") is not None or k.get("voices"))]
        named = {v["at"] for e in entries for v in e.get("voices", []) if v["by"] == "transcript"}
        for clip, sc in clips.items():  # each clip's voices that match a known person's are theirs, unless you named them
            said = sc.get("transcript", {}).get("voices", [])
            at = library.name_of(clip)
            if at in named:
                continue
            entries = heard(entries, at, {n: [{**v, "by": "build"}]
                                          for v, n in zip(said, names([v["print"] for v in said], entries, at)) if n})
        known_voices = {(v["at"], v["voice"]) for e in entries for v in e.get("voices", [])}
        unheard = [{"at": library.name_of(clip), **v, "by": "build"} for clip, sc in clips.items()
                   for v in sc.get("transcript", {}).get("voices", [])
                   if v["seconds"] >= HEARD and (library.name_of(clip), v["voice"]) not in known_voices]
        return sorted(strangers(entries, unheard), key=lambda e: e["id"])

    entries = update(lib, change)
    report.append(("people", f"{len(entries)} people", f"{sum(len(e['clips']) > 1 for e in entries)} in more than one clip"))


def strangers(entries: list, unheard: list) -> list:
    """The entries with the voices nobody named grouped into people across files: complete linkage, so every two
    voices of one person are at least VOICE alike. A group keeps the id of the last build's group it sounds like; an
    unnamed voice-only entry whose voice is no longer heard is dropped, since nothing in it was decided by anyone."""
    stranger = lambda e: not e.get("name") and not e.get("print") and e.get("skin_stops") is None
    before = [(e["id"], centre(e["voices"])) for e in entries if stranger(e) and e.get("voices")]
    entries = [e for e in entries if not stranger(e)]
    groups: list = []
    if len(unheard) > 1:
        from scipy.cluster.hierarchy import fcluster, linkage
        cut = fcluster(linkage(np.array([unit(v["print"]) for v in unheard]), method="complete", metric="cosine"),
                       t=1 - VOICE, criterion="distance")
        groups = [[unheard[i] for i in np.nonzero(cut == g)[0]] for g in sorted(set(cut))]
    elif unheard:
        groups = [unheard]
    used: set = set()
    for g in sorted(groups, key=lambda g: -sum(v["seconds"] for v in g)):
        c = centre(g)
        old = max(((float(c @ p), i) for i, p in before if i not in used), default=(0.0, None))
        taken = {e["id"] for e in entries} | used
        pid = old[1] if old[0] >= VOICE else next(f"p{i:02d}" for i in range(1, 9999) if f"p{i:02d}" not in taken)
        used.add(pid)
        entries.append({"id": pid, "name": None, "skin_stops": None, "clips": [], "print": None,
                        "voices": [{**v, "print": [round(float(x), 4) for x in v["print"]]} for v in g]})
    return entries


def centre(prints: list) -> np.ndarray:
    """One voice from several of its prints, each weighted by the seconds it was heard."""
    return unit(np.sum([unit(v["print"]) * v["seconds"] for v in prints], axis=0))


def voices(entries: list, besides: str | None = None) -> dict:
    """Each named person's voice: the mean of their voiceprints, weighted by the seconds each was heard, leaving out
    the prints from `besides` (a file is matched only against what other files taught)."""
    prints: dict = {}
    for e in entries:
        for v in e.get("voices", []):
            if e.get("name") and v["at"] != besides:
                prints.setdefault(e["name"], []).append(unit(v["print"]) * v["seconds"])
    return {name: unit(np.sum(ps, axis=0)) for name, ps in prints.items()}


def names(prints: list, entries: list, at: str) -> list:
    """Who each of one file's voices is: the known person whose voice its print matches best, if at least VOICE, each
    person at most once, the most alike pairs first; None for a voice nobody matches."""
    known = voices(entries, at)
    pairs = sorted(((float(unit(p) @ v), i, n) for i, p in enumerate(prints) for n, v in known.items()), reverse=True)
    out: list = [None] * len(prints)
    for score, i, n in pairs:
        if score >= VOICE and out[i] is None and n not in out:
            out[i] = n
    return out


def heard(entries: list, at: str, named: dict) -> list:
    """The entries with the voiceprints from file `at` replaced by `named` (name: its prints), so a renamed voice's
    print moves to its new name. A print goes to the first entry with that name, or to a new one."""
    for e in entries:
        e["voices"] = [v for v in e.get("voices", []) if v["at"] != at]
    for name, prints in named.items():
        e = next((e for e in sorted(entries, key=lambda e: e["id"]) if e.get("name") == name), None)
        if e is None:
            taken = {k["id"] for k in entries}
            e = {"id": next(f"p{i:02d}" for i in range(1, 999) if f"p{i:02d}" not in taken), "name": name,
                 "skin_stops": None, "clips": [], "print": None, "voices": []}
            entries.append(e)
        e["voices"] += [{"at": at, **v, "print": [round(float(x), 4) for x in v["print"]]} for v in prints]
    return entries


def at(media: Path, lib: Path) -> str:
    """The one name a recording's voiceprints are recorded under: DAY/FILE for a Library clip, else its full path."""
    media = media.resolve()
    return library.name_of(media) if media.parent.parent == lib.resolve() else str(media)


def voiced(clip: Path, sc: dict) -> dict:
    """Who the clip's voices are, by voice id: the person a print from this clip was recorded under (their name, or
    their id while nobody has named them), when it is the print of a voice in the clip's transcript as it is now, so a
    transcript redone since names nobody until the next build, and a voice named in a transcript of the clip is named
    here too."""
    recorded = [(v["print"], e["name"] or e["id"]) for e in known(clip.parent.parent / "people.json") for v in e.get("voices", [])
                if v["at"] == library.name_of(clip)]
    return {v["voice"]: name for v in sc.get("transcript", {}).get("voices", []) for p, name in recorded
            if v["print"] == p}


def called(person: str, lib: Path) -> set:
    """Every form a person may be asked for by: the id or name given, and the names of entries with that id."""
    return {person} | {e["name"] for e in known(lib / "people.json") if e["id"] == person and e.get("name")}


@cache
def known(path: Path) -> list[dict]:
    return json.loads(path.read_text())["people"] if path.exists() else []


def of(clip: Path, sc: dict) -> dict | None:
    """The clip's subject (the largest face measured), if they are one of the people the last build found in this clip:
    id, name and skin level."""
    subject = sc.get("measured", {}).get("face")
    if not subject:
        return None
    s = unit(subject["print"])
    here = [p for p in known(clip.parent.parent / "people.json") if p.get("print") and library.name_of(clip) in p["clips"]]
    p = max(here, key=lambda p: float(unit(p["print"]) @ s), default=None)
    if p is None or float(unit(p["print"]) @ s) < face.SAME:
        return None
    return {"id": p["id"], "name": p["name"], "skin_stops": p["skin_stops"]}
