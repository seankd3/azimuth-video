"""Find shots in the Library: every clip whose sidecar matches all the words and filters, one line each.

Words match anywhere in what the toolkit knows about a clip: its description, tags, moments, transcript and the
person's name. Each line shows where the usable parts are: the steady stretches (from the shake pass) and the
focus pulls, so a shot can be cut straight from the list.

python -m footage.find hands wire --size close-up --steady
python -m footage.find --person p01 --json
"""
import argparse
import json
from pathlib import Path

from . import library, sidecar
from .steady import SHAKE_MIN

STEADY_SECONDS = 2  # shortest steady stretch worth listing


def steady(sc: dict) -> list[tuple[int, int]] | None:
    """Stretches of at least STEADY_SECONDS whole seconds where the camera holds still (or moves smoothly); None if unmeasured."""
    if "shake" not in sc:
        return None
    runs, start, end = [], None, sc["facts"]["duration"]  # the last second may be partial: stretches stop at the clip's end
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
             *(seg.get("text", "") for seg in t.get("segments", [])), (sc.get("person") or {}).get("name") or ""]
    return " ".join(words).lower()


def record(clip: Path, sc: dict) -> dict:
    d = sc.get("description", {})
    return {"clip": str(clip), "name": f"{clip.parent.name}/{clip.stem}", "seconds": round(sc["facts"]["duration"], 1),
            "size": d.get("shot_size"), "summary": d.get("summary"), "tags": d.get("tags", []),
            "person": sc.get("person"), "steady": steady(sc),
            "pulls": [(p["start"], p["end"], p["kind"]) for p in sc.get("focus", {}).get("pulls", [])],
            "speech": [(s["start"], s["end"], s.get("text", "")) for s in sc.get("transcript", {}).get("segments", [])]}


def matches(sc: dict, a) -> bool:
    d, who = sc.get("description", {}), sc.get("person") or {}
    return (all(w.lower() in text(sc) for w in a.words)
            and (not a.size or d.get("shot_size") == a.size)
            and (not a.person or a.person in (who.get("id"), who.get("name")))
            and (not a.steady or bool(steady(sc)))
            and (not a.pulls or bool(sc.get("focus", {}).get("pulls"))))


def line(r: dict) -> str:
    where = ([f"steady {', '.join(f'{a}-{b:.1f}s'.replace('.0s', 's') for a, b in r['steady'])}"] if r["steady"] else
             ["handheld"] if r["steady"] == [] else []) + \
            ([f"pulls {', '.join(f'{a:.1f}-{b:.1f}s' for a, b, _ in r['pulls'])}"] if r["pulls"] else []) + \
            ([f"speech {len(r['speech'])}"] if r["speech"] else [])
    who = (r["person"] or {}).get("name") or (r["person"] or {}).get("id") or ""
    return f"{r['name']:22} {r['seconds']:5.1f}s {r['size'] or '?':8} {who:6} {'; '.join(where):34} {r['summary']}"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="footage.find")
    ap.add_argument("words", nargs="*")
    ap.add_argument("--library", type=Path, default=Path.home() / "Videos/Library")
    ap.add_argument("--size", choices=["close-up", "medium", "wide"])
    ap.add_argument("--person", help="a person's id or name from people.json")
    ap.add_argument("--steady", action="store_true", help="only clips with a steady stretch")
    ap.add_argument("--pulls", action="store_true", help="only clips with a focus pull")
    ap.add_argument("--day", help="shooting day, YYYY-MM-DD")
    ap.add_argument("--json", action="store_true", help="full records, for an agent")
    a = ap.parse_args()
    found = [record(c, sc) for c in library.clips(a.library)
             if (not a.day or c.parent.name == a.day) and (sc := sidecar.read(c)) and matches(sc, a)]  # folders are days
    print(json.dumps(found, indent=1) if a.json else "\n".join(map(line, found)) + f"\n{len(found)} clips")
