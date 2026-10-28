"""Who appears across the Library: faces grouped into people by fingerprint, with what you've said about each.

`people.json` beside the day folders lists each person: an id, the clips they're in, a fingerprint, and two things only
you fill in: a `name`, and `skin_stops`, where their lit cheek should sit (stops above 18% grey). Skin level is a
judgement, not a measurement: no frame can tell darker skin from underexposure, so the machine never guesses it.
Entries that share a name are one person. Rebuilding keeps ids, names and skin levels. A clip whose subject is a known
person gets a `person` section, which exposure reads.
"""
import json
import os
from pathlib import Path

import numpy as np

from . import library, sidecar

SAME = 0.363  # SFace cosine similarity at which two faces are the same person (OpenCV's recommended threshold)
ACROSS = 0.45  # stricter across clips, comparing every member: splitting one person is harmless, merging two is not


def unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def tracks(measured: dict) -> list[dict]:
    """The distinct faces in one clip: its detections grouped by fingerprint."""
    out = []
    for d in sorted(measured.get("faces", []), key=lambda d: -d["height"]):
        p = unit(d["print"])
        best = max(out, key=lambda t: float(t["print"] @ p), default=None)
        if best is not None and float(best["print"] @ p) >= SAME:
            best["members"].append(d)
            best["print"] = unit(np.mean([unit(m["print"]) for m in best["members"]], axis=0))
        else:
            out.append({"print": p, "members": [d]})
    for t in out:
        t["key_stops"] = float(np.median([m["key_stops"] for m in t["members"]]))
        t["height"] = max(m["height"] for m in t["members"])
    return out


def build(lib: Path, report: list) -> None:
    path = lib / "people.json"
    known = json.loads(path.read_text())["people"] if path.exists() else []
    clips = {}
    for clip in library.clips(lib):
        try:
            sc = sidecar.read(clip)
        except ValueError:
            continue
        if sc and "measured" in sc:
            clips[clip] = sc
    found = [(clip, t) for clip, sc in clips.items() for t in tracks(sc["measured"])]
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
    # Carry ids and names over from the last build; new people get the next free id.
    used = set()
    for p in people:
        match = max((k for k in known if k["id"] not in used), key=lambda k: float(unit(k["print"]) @ p["print"]), default=None)
        if match is not None and float(unit(match["print"]) @ p["print"]) >= SAME:
            p["id"], p["name"], p["skin_stops"] = match["id"], match.get("name"), match.get("skin_stops")
        else:
            taken = {k["id"] for k in known} | {q.get("id") for q in people}
            p["id"], p["name"], p["skin_stops"] = next(f"p{i:02d}" for i in range(1, 999) if f"p{i:02d}" not in taken), None, None
        used.add(p["id"])
        p["clips"] = sorted({clip.stem for clip, _ in p["tracks"]})
    for p in people:  # a skin level given to one entry of a named person holds for all of them
        p["skin_stops"] = next((q["skin_stops"] for q in people if q["skin_stops"] is not None and p["name"]
                                and q["name"] == p["name"]), p["skin_stops"])
    entries = [{"id": p["id"], "name": p["name"], "skin_stops": p["skin_stops"], "clips": p["clips"],
                "print": [round(float(v), 3) for v in p["print"]]} for p in sorted(people, key=lambda p: p["id"])]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"people": entries}, indent=1))
    os.rename(tmp, path)
    # Each clip's subject, if they are a known person.
    for clip, sc in clips.items():
        subject = sc["measured"].get("face")
        person = None
        if subject:
            p = max(people, key=lambda p: float(p["print"] @ unit(subject["print"])), default=None)
            if p is not None and float(p["print"] @ unit(subject["print"])) >= SAME:
                person = {"id": p["id"], "name": p["name"], "skin_stops": p["skin_stops"]}
        if sc.get("person") != person:
            sidecar.write(clip, {**{k: v for k, v in sc.items() if k != "person"}, **({"person": person} if person else {})})
    report.append(("people", f"{len(entries)} people", f"{sum(len(e['clips']) > 1 for e in entries)} in more than one clip"))
