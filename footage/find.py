"""Find shots in the Library: every clip whose sidecar matches all the words and filters, one line each.

Words match anywhere in what the toolkit knows about a clip: its description, tags, moments, transcript, the
person's name and the names of the voices heard. Each line shows where the usable parts are: the steady stretches (from the shake pass) and the
focus pulls, so a shot can be cut straight from the list. Sections that are out of date are left out of the search,
and the count of clips that had any is printed after the results.

With --shows, --sounds or --like the answer is moments rather than clips: the windows of the clips found whose picture
or sound is nearest a phrase, or whose picture is nearest a moment of another clip (embed.py), nearest first, each with
its seconds and how near it is.

python -m footage.find hands wire --size close-up --steady
python -m footage.find --person p01 --json
python -m footage.find --shows "a forklift backing up" --steady
python -m footage.find --sounds "a grinder" --day 2026-11-03
python -m footage.find --like 2026-10-29/CLIP0001@12
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

from . import embed, library, passes, people, sidecar
from .frame import seconds
from .steady import SHAKE_MIN, handheld
from .transcribe.formats import turns

STEADY_SECONDS = 2  # shortest steady stretch worth listing


def steady(sc: dict) -> list[tuple[int, int]] | None:
    """Stretches of at least STEADY_SECONDS whole seconds where the camera holds still (or moves smoothly); None if unmeasured."""
    end = sc["facts"]["duration"]
    if not handheld(sc):  # on a tripod the whole clip holds still; any motion measured is the subject's
        return [(0, end)]
    if "shake" not in sc:
        return None
    runs, start = [], None  # the last second may be partial: stretches stop at the clip's end
    for s, px in enumerate(sc["shake"]["by_second"] + [None]):
        if px is not None and px < SHAKE_MIN:
            start = s if start is None else start
        else:
            if start is not None and min(s, end) - start >= STEADY_SECONDS:
                runs.append((start, min(s, end)))
            start = None
    return runs


def text(sc: dict) -> str:
    d, t = sc.get("description", {}), sc.get("transcript", {})
    words = [d.get("summary", ""), d.get("action", ""), d.get("setting", ""), d.get("shot_size", ""), d.get("camera_movement", ""),
             *d.get("subjects", []), *d.get("tags", []), *(m["what"] for m in d.get("moments", [])),
             *(w["text"] for w in t.get("words", [])), (sc.get("person") or {}).get("name") or "",
             *sc.get("voices", {}).values()]
    return " ".join(words).lower()


def record(clip: Path, sc: dict) -> dict:
    d = sc.get("description", {})
    return {"clip": str(clip), "name": f"{clip.parent.name}/{clip.stem}", "seconds": round(sc["facts"]["duration"], 1),
            "size": d.get("shot_size"), "summary": d.get("summary"), "tags": d.get("tags", []),
            "person": sc.get("person"), "voices": sc.get("voices", {}), "steady": steady(sc),
            "pulls": [(p["start"], p["end"], p["kind"]) for p in sc.get("focus", {}).get("pulls", [])],
            "speech": [(t["start"], t["end"], t["text"]) for t in turns(sc.get("transcript", {}).get("words", []))]}


def matches(sc: dict, a, wanted: set) -> bool:
    d, who = sc.get("description", {}), sc.get("person") or {}
    return (all(w.lower() in text(sc) for w in a.words)
            and (not a.size or d.get("shot_size") == a.size)
            and (not a.person or bool(wanted & {who.get("id"), who.get("name"), *sc.get("voices", {}).values()}))
            and (not a.steady or bool(steady(sc)))
            and (not a.pulls or bool(sc.get("focus", {}).get("pulls"))))


def line(r: dict) -> str:
    where = ([f"steady {', '.join(f'{a}-{b:.1f}s'.replace('.0s', 's') for a, b in r['steady'])}"] if r["steady"] else
             ["handheld"] if r["steady"] == [] else []) + \
            ([f"pulls {', '.join(f'{a:.1f}-{b:.1f}s' for a, b, _ in r['pulls'])}"] if r["pulls"] else []) + \
            ([f"speech {len(r['speech'])}"] if r["speech"] else [])
    who = (r["person"] or {}).get("name") or (r["person"] or {}).get("id") or ""
    return f"{r['name']:22} {r['seconds']:5.1f}s {r['size'] or '?':8} {who:6} {'; '.join(where):34} {r['summary']}"


def query(a) -> tuple[str, np.ndarray, Path | None] | None:
    """What the moments are ranked by: the kind of window, the vector to be near, and the clip it came from."""
    if a.shows or a.sounds:
        return ("picture" if a.shows else "sound"), embed.phrase(a.shows or a.sounds), None
    if a.like:
        name, at = a.like.rsplit("@", 1)
        clip = next((c for c in library.clips(a.library) if f"{c.parent.name}/{c.stem}" == name), None)
        if clip is None or (sc := sidecar.read(clip)) is None:
            raise SystemExit(f"--like: no filed clip {name} in {a.library}")
        rows = passes.fresh(clip, sc)[0].get("embedding", {}).get("picture")
        if not rows:
            raise SystemExit(f"--like: {name} has no current embedding: run python -m footage")
        return "picture", np.array(rows[min(int(seconds(at) // embed.WINDOW), len(rows) - 1)]), clip
    return None


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="footage.find")
    ap.add_argument("words", nargs="*")
    ap.add_argument("--library", type=Path, default=Path.home() / "Videos/Library")
    ap.add_argument("--size", choices=["close-up", "medium", "wide"])
    ap.add_argument("--person", help="a person's id or name from people.json, seen or heard")
    ap.add_argument("--steady", action="store_true", help="only clips with a steady stretch")
    ap.add_argument("--pulls", action="store_true", help="only clips with a focus pull")
    ap.add_argument("--day", help="shooting day, YYYY-MM-DD")
    ap.add_argument("--json", action="store_true", help="full records, for an agent")
    near = ap.add_mutually_exclusive_group()
    near.add_argument("--shows", metavar="PHRASE", help="moments whose picture matches the phrase")
    near.add_argument("--sounds", metavar="PHRASE", help="moments whose sound matches the phrase")
    near.add_argument("--like", metavar="DAY/CLIP@SECONDS", help="moments that look like that moment of another clip")
    ap.add_argument("--top", type=int, default=20, help="how many moments (with --shows, --sounds or --like)")
    a = ap.parse_args()
    q = query(a)
    found, behind = [], 0
    wanted = people.called(a.person, a.library) if a.person else set()
    for c in library.clips(a.library):
        if (a.day and c.parent.name != a.day) or (sc := sidecar.read(c)) is None:  # folders are days
            continue
        sc, stale = passes.fresh(c, sc)
        behind += bool(stale)
        sc["person"], sc["voices"] = people.of(c, sc), people.voiced(c, sc)
        if matches(sc, a, wanted) and not (q and c == q[2]):
            found.append((record(c, sc), sc))
    if q:
        out = embed.nearest(found, q[0], q[1], a.top)
        print(json.dumps(out, indent=1) if a.json else "\n".join(
            f"{m['start']:6.1f}-{m['end']:<6.1f} {m['near']:.2f}  {line(m)}" for m in out) + f"\n{len(out)} moments")
    else:
        found = [r for r, _ in found]
        print(json.dumps(found, indent=1) if a.json else "\n".join(map(line, found)) + f"\n{len(found)} clips")
    if behind:
        print(f"{behind} clips have out-of-date sections, searched without them: run python -m footage", file=sys.stderr)
