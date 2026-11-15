"""azimuth_theme: choose an Azimuth theme in a Python app, and notice when it changes.

Vendored into each app by azimuth-design (`python3 -m azimuth_design vendor DEST`), beside
themes/*.json. Stdlib only. Do not edit the vendored copy; change azimuth-design and re-vendor.

    import azimuth_theme as az
    theme = az.choose(picked=None, system_dark=True)   # a theme file, as a dict
    theme["colors"]["panel"]                           # "#0e0e10"
    az.RUNTIME                                         # the file to watch for live Omarchy themes

Which theme: the owner's pick if there is one; else, on Omarchy, the live Omarchy theme
(rendered to RUNTIME on every theme change); else Azimuth Dark or Light, following the system.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

FORMAT = 1
HERE = Path(__file__).resolve().parent
THEMES = HERE / "themes"
RUNTIME = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "azimuth/theme.json"
OMARCHY = "omarchy"
DARK, LIGHT = "azimuth-dark", "azimuth-light"


def read(path: Path) -> dict | None:
    """A theme file, or None if it is missing, half-written, or newer than this app knows."""
    try:
        t = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(t, dict) or t.get("format", 0) > FORMAT or not isinstance(t.get("colors"), dict):
        return None
    return t


def built_ins() -> dict[str, dict]:
    """The built-in themes, by id."""
    out = {}
    for p in sorted(THEMES.glob("*.json")):
        t = read(p)
        if t:
            out[t["id"]] = t
    return out


def runtime() -> dict | None:
    """The live Omarchy theme, if this machine runs Omarchy with azimuth-design's hook."""
    return read(RUNTIME)


def choices() -> list[tuple[str, str]]:
    """(id, name) for a theme picker: the live Omarchy theme first when there is one."""
    out = []
    live = runtime()
    if live:
        out.append((OMARCHY, f"Omarchy ({live['name']})"))
    out += [(i, t["name"]) for i, t in built_ins().items()]
    return out


def choose(picked: str | None = None, system_dark: bool = True) -> dict:
    """The theme to draw with. picked is a theme id, "omarchy", or None/"system" for the default."""
    themes = built_ins()
    if picked in themes:
        return themes[picked]
    if picked in (None, "", "system", OMARCHY):
        live = runtime()
        if live:
            return live
    return themes[DARK if system_dark else LIGHT]
