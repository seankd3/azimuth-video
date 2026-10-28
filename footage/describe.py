"""Describe one filed clip with the local vision model, from desqueezed frames sampled across the take."""
import base64
import json
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config

ENDPOINT = "http://127.0.0.1:1234/v1/chat/completions"
MODEL = "qwen/qwen3.5-35b-a3b"
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


def available() -> bool:
    """Whether the local server offers MODEL; without it there is nothing to describe with, so skip quickly."""
    try:
        listed = json.load(urllib.request.urlopen(ENDPOINT.replace("chat/completions", "models"), timeout=5))
    except OSError:
        return False
    return any(m["id"] == MODEL for m in listed["data"])


def times(duration: float) -> list[float]:
    n = min(max(round(duration / 5), 4), 16)
    return [round(duration * (i + 0.5) / n, 2) for i in range(n)]


def frame(clip: Path, t: float, squeeze: float, width: int, height: int) -> str:
    h = round(WIDTH * height / (width * squeeze) / 2) * 2
    jpg = subprocess.run(["ffmpeg", "-v", "error", "-threads", "1", "-ss", f"{t:.2f}", "-i", str(clip), "-frames:v", "1",
                          "-vf", f"scale={WIDTH}:{h},setsar=1", "-q:v", "4", "-f", "image2pipe", "-c:v", "mjpeg", "-"],
                         capture_output=True, check=True).stdout
    return base64.b64encode(jpg).decode()


def valid_moments(moments: list, duration: float) -> list:
    out = []
    for m in moments:
        start, end = max(0.0, float(m["start"])), min(duration, float(m["end"]))
        if start < end:
            out.append({"start": round(start, 2), "end": round(end, 2), "what": m["what"]})
    return out


def describe(clip: Path, sc: dict) -> dict:
    f, squeeze = sc["facts"], sc["assumed"]["squeeze"]
    ts = times(f["duration"])
    with ThreadPoolExecutor(8) as pool:
        frames = list(pool.map(lambda t: frame(clip, t, squeeze, f["width"], f["height"]), ts))
    context = config.load().get("context")
    text = PROMPT.format(n=len(ts), dur=f["duration"], times=", ".join(f"{t:g}" for t in ts),
                         context=f" {context}" if context else "")
    content = [{"type": "text", "text": text}]
    content += [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b}"}} for b in frames]
    body = {"model": MODEL, "temperature": 0.2, "reasoning_effort": "none", "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "take", "strict": True, "schema": SCHEMA}}}
    req = urllib.request.Request(ENDPOINT, json.dumps(body).encode(), {"Content-Type": "application/json"})
    reply = json.load(urllib.request.urlopen(req, timeout=900))
    d = json.loads(reply["choices"][0]["message"]["content"])
    d["moments"] = valid_moments(d["moments"], f["duration"])
    return {"model": MODEL, "squeeze_used": squeeze, "frames_at": ts, **d}
