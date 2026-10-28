"""Settings for one site, kept outside the repository: what the footage shows, camera rules, and the timezone.

The file is `~/.config/azimuth-video/config.json`, or the path in AZIMUTH_VIDEO_CONFIG. Every key is optional:

    {
      "context": "One sentence about what the footage shows, given to the description model.",
      "timezone": "Area/City",
      "cameras": [{"model_prefix": "Canon EOS", "squeeze": 1.6, "log": "Canon Log 3", "gamut": "Cinema Gamut"}]
    }

Without a timezone, shooting days follow the system's local time. Without a camera rule, a clip's squeeze is unknown
until you set it in its sidecar.
"""
import json
import os
from functools import cache
from pathlib import Path


@cache
def load() -> dict:
    path = Path(os.environ.get("AZIMUTH_VIDEO_CONFIG", Path.home() / ".config/azimuth-video/config.json"))
    return json.loads(path.read_text()) if path.exists() else {}
