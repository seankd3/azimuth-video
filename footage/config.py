"""Settings for one site, kept outside the repository: what the footage shows, camera rules, timezone, house look.

The file is `~/.config/azimuth-video/config.json`, or the path in AZIMUTH_VIDEO_CONFIG. Every key is optional:

    {
      "context": "One sentence about what the footage shows, given to the describer.",
      "describer": "agent or model name",
      "timezone": "Area/City",
      "look": "cinema-glow",
      "cameras": [{"model_prefix": "Canon EOS", "squeeze": 1.6, "log": "Canon Log 3", "gamut": "Cinema Gamut"}],
      "theme": "system"
    }

`describer` names who answers the description questions (see describe.py). Without a timezone, shooting days follow
the system's local time. `look` is the house look (a file in looks/) that every render and still uses unless a timeline
or --look names another; without it, cinema-glow. Without a camera rule, a clip's squeeze is unknown until you set it with
python -m footage.assume.
`theme` is the app's look: "system" (the live Omarchy theme, else dark or light as the system is), "azimuth-dark" or
"azimuth-light". The app writes it when the theme is picked in its window (`save`).
"""
import json
import os
from functools import cache
from pathlib import Path


def path() -> Path:
    return Path(os.environ.get("AZIMUTH_VIDEO_CONFIG", Path.home() / ".config/azimuth-video/config.json"))


@cache
def load() -> dict:
    return json.loads(path().read_text()) if path().exists() else {}


def save(key: str, value) -> None:
    """Set one key, keeping the rest of the file as it is, written so a reader never sees half a file."""
    p = path()
    data = json.loads(p.read_text()) if p.exists() else {}
    if data.get(key) == value:
        return
    data[key] = value
    p.parent.mkdir(parents=True, exist_ok=True)
    part = p.with_name(p.name + ".part")
    part.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    part.replace(p)
    load.cache_clear()
