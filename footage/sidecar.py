"""One JSON file beside each clip, holding everything known about it: facts, assumptions, description."""
import json
import os
from pathlib import Path

VERSION = 1


def path_for(media: Path) -> Path:
    # The full media name, so A.MP4 and A.MOV never share a sidecar.
    return media.with_name(media.name + ".json")


def read(media: Path) -> dict | None:
    """The sidecar, or None if there is none. Anything unreadable or misshapen raises ValueError, so callers
    handle one kind of failure."""
    try:
        data = json.loads(path_for(media).read_text())
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"unreadable: {e}") from e
    f = data.get("facts") if isinstance(data, dict) else None
    a = data.get("assumed") if isinstance(data, dict) else None
    if not (isinstance(data, dict) and data.get("version") == VERSION
            and isinstance(f, dict) and isinstance(f.get("sha256"), str) and isinstance(f.get("size"), int)
            and isinstance(f.get("duration"), (int, float)) and isinstance(a, dict) and "squeeze" in a
            and isinstance(data.get("description", {}), dict)):
        raise ValueError("not a footage v1 sidecar")
    return data


def write(media: Path, data: dict) -> None:
    """Replace the sidecar atomically and durably: temp file, fsync, rename, fsync the folder."""
    data = {"version": VERSION, **{k: v for k, v in data.items() if k != "version"}}
    final = path_for(media)
    tmp = final.with_name(final.name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp, final)
    sync_dir(final.parent)


def sync_dir(folder: Path) -> None:
    fd = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
