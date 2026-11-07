"""Describe one filed clip: the toolkit asks a question about desqueezed frames sampled across the take, and whoever
the site names as its describer (an agent, or a vision model with a small script around it) answers it.

A question is a folder, LIBRARY/.questions/DAY/FILE/KEY/: the frames in order and question.json, which holds the prompt
and the answer's schema. KEY names what the question was asked from (the description's id and the clip's bytes), so an
answer always belongs to the question in its folder; new inputs are a new question. The describer writes answer.json
beside them. The next run checks it and stores it, then retires the question.
"""
import hashlib
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path

from . import config, sidecar, view
from .frame import jpeg

VERSION = 1  # bump when the prompt, schema or frame sampling changes

WIDTH = 1280

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["summary", "shot_size", "camera_movement", "subjects", "action", "setting", "people_count",
                 "gear_in_frame", "moments", "tags"],
    "properties": {
        "summary": {"type": "string"},
        "shot_size": {"enum": ["extreme close-up", "close-up", "medium", "wide", "extreme wide", "mixed"]},
        "camera_movement": {"enum": ["static", "pan", "tilt", "push in", "pull out", "tracking", "handheld", "mixed"]},
        "subjects": {"type": "array", "items": {"type": "string"}},
        "action": {"type": "string"},
        "setting": {"type": "string"},
        "people_count": {"type": "integer"},
        "gear_in_frame": {"type": "boolean"},
        "moments": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["start", "end", "what"],
            "properties": {"start": {"type": "number"}, "end": {"type": "number"}, "what": {"type": "string"}}}},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
}

PROMPT = (
    "These {n} frames are samples from one continuous {dur:.1f}-second B-roll take.{context} "
    "The footage may be flat log, so colours can look washed out; ignore that. "
    "Frame timestamps in seconds, in order: {times}. "
    "Describe the take for a video editor searching for promo B-roll. Report only what the frames show. "
    "gear_in_frame: true when film lights, stands or other crew gear are visible. "
    "moments: up to 4 stretches worth cutting to; start and end are approximate and must be sample timestamps "
    "(or 0 and {dur:.1f}); describe what the frames inside each stretch show. "
    "Be terse: summary under 25 words, each moment under 12 words, subjects as short noun phrases, at most 10 tags."
)


def identity(sc: dict) -> dict:
    """Who answers is a setting, so naming a new describer redoes every description."""
    site = config.load()
    context = site.get("context") or ""
    return {"describe": VERSION, "describer": site.get("describer"), "context": hashlib.sha1(context.encode()).hexdigest()[:12],
            **view.identity(sc)}


def times(duration: float) -> list[float]:
    n = min(max(round(duration / 5), 4), 16)
    return [round(duration * (i + 0.5) / n, 2) for i in range(n)]


def frame(clip: Path, sc: dict, t: float, out: Path) -> None:
    out.write_bytes(jpeg(clip, sc, t, WIDTH))


def valid_moments(moments: list, duration: float) -> list:
    out = []
    for m in moments:
        start, end = max(0.0, float(m["start"])), min(duration, float(m["end"]))
        if start < end:
            out.append({"start": round(start, 2), "end": round(end, 2), "what": m["what"]})
    return out


def misfit(value, schema: dict, at: str = "answer") -> str | None:
    """What in `value` breaks `schema` (the part of JSON Schema that SCHEMA uses), or None."""
    if "enum" in schema:
        return None if value in schema["enum"] else f"{at} is not one of {schema['enum']}"
    kind = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool}[schema["type"]]
    if not isinstance(value, kind) or (isinstance(value, bool) and schema["type"] != "boolean"):
        return f"{at} is not {schema['type']}"
    if schema["type"] == "object":
        if set(value) != set(schema["required"]):
            return f"{at} needs exactly the keys {schema['required']}"
        return next((m for k, v in value.items() if (m := misfit(v, schema["properties"][k], f"{at}.{k}"))), None)
    if schema["type"] == "array":
        return next((m for i, v in enumerate(value) if (m := misfit(v, schema["items"], f"{at}[{i}]"))), None)
    return None


def question(clip: Path, sc: dict) -> Path:
    """Where the clip's question for its current inputs lives."""
    key = hashlib.sha1(json.dumps([identity(sc), sc["facts"]["sha256"]], sort_keys=True).encode()).hexdigest()[:12]
    return clip.parent.parent / ".questions" / clip.parent.name / clip.name / key


def ask(clip: Path, sc: dict, here: Path) -> None:
    """Write the question beside its place and move it in whole, so a question folder is always complete."""
    part = here.with_name(here.name + ".part")
    shutil.rmtree(part, ignore_errors=True)
    part.mkdir(parents=True)
    ts = times(sc["facts"]["duration"])
    names = [f"{i:02d}.jpg" for i in range(1, len(ts) + 1)]
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda t, name: frame(clip, sc, t, part / name), ts, names))
    context = config.load().get("context")
    prompt = PROMPT.format(n=len(ts), dur=sc["facts"]["duration"], times=", ".join(f"{t:g}" for t in ts),
                           context=f" {context}" if context else "")
    (part / "question.json").write_text(json.dumps(
        {"prompt": prompt, "frames": names, "answer": "Write one JSON object that fits schema to answer.json here.",
         "schema": SCHEMA}, indent=1))
    part.rename(here)


def describe(clip: Path, sc: dict) -> dict | None:
    """The clip's description from the answer to its current question, or None while that question waits for one."""
    here = question(clip, sc)
    if not here.exists():
        ask(clip, sc, here)
        return None
    try:
        d = json.loads((here / "answer.json").read_text())
    except FileNotFoundError:
        return None
    if problem := misfit(d, SCHEMA):
        raise ValueError(f"{here / 'answer.json'}: {problem}")
    d["moments"] = valid_moments(d["moments"], sc["facts"]["duration"])
    return {"frames_at": times(sc["facts"]["duration"]), **d}


def retire(library: Path) -> None:
    """Remove each question whose answer is stored, or that its clip would no longer be asked, and anything else beside
    the questions (a describer's stray file is not a question)."""
    for here in library.glob(".questions/*/*/*"):
        clip = library / here.parent.parent.name / here.parent.name
        try:
            sc = sidecar.read(clip)
        except ValueError:
            continue  # the passes report the sidecar; its question waits
        if sc is None or here != question(clip, sc) or sc.get("description", {}).get("id") == identity(sc):
            if here.is_dir() and not here.is_symlink():
                shutil.rmtree(here)
            else:
                here.unlink()
    for empty in [*library.glob(".questions/*/*"), *library.glob(".questions/*")]:
        with suppress(OSError):
            empty.rmdir()
