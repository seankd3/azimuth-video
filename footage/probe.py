"""Measured facts about one media file, and whether a copy into the inbox has finished."""
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import config

VIDEO = {".mp4", ".mov"}


def is_video(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in VIDEO


def open_files() -> set[tuple[int, int]]:
    """Every (device, inode) some process holds open, e.g. a file manager still copying into the inbox."""
    held = set()
    for fd_dir in Path("/proc").glob("[0-9]*/fd"):
        try:
            for fd in fd_dir.iterdir():
                try:
                    s = fd.stat()
                except OSError:
                    continue
                held.add((s.st_dev, s.st_ino))
        except OSError:
            continue
    return held


def ffprobe(p: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(p)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def complete(p: Path) -> bool:
    """MP4/MOV files are a chain of boxes that each declare their size. A finished copy ends exactly at the end of
    its last box and contains the media box (mdat). A copy cut short, even right after the index, fails this."""
    size, pos, media = p.stat().st_size, 0, False
    with open(p, "rb") as f:
        while pos < size:
            f.seek(pos)
            h = f.read(16)
            n = int.from_bytes(h[:4], "big") if len(h) >= 8 else -1
            if n == 1:
                n = int.from_bytes(h[8:16], "big") if len(h) == 16 else -1
            if n < 8:  # also n == 0, "runs to end of file": its length can't be checked
                return False
            media |= h[4:8] == b"mdat"
            pos += n
    return pos == size and media


def ready(p: Path, held: set[tuple[int, int]]) -> tuple[bool, str]:
    """Take the open-file snapshot after listing the inbox, so a listed file is either still held or finished."""
    st = p.stat()
    if (st.st_dev, st.st_ino) in held:
        return False, "still open in another program"
    if not complete(p):
        return False, "incomplete: fewer bytes than the file declares"
    return True, ""


def sha256(p: Path) -> str:
    """Hash without filling the page cache: tens of GB of footage would push the loaded model out of memory."""
    h = hashlib.sha256()
    with open(p, "rb") as f:
        done = 0
        while chunk := f.read(8 << 20):
            h.update(chunk)
            os.posix_fadvise(f.fileno(), done, len(chunk), os.POSIX_FADV_DONTNEED)
            done += len(chunk)
    return h.hexdigest()


def camera(p: Path, tags: dict) -> str | None:
    with open(p, "rb") as f:
        m = re.search(rb"Canon EOS [\w .-]{1,24}", f.read(4096))
    if m:
        return m.group().split(b"\x00")[0].decode().strip()
    make = next((v for k, v in tags.items() if k.lower().endswith("make")), "").strip()
    model = next((v for k, v in tags.items() if k.lower().endswith("model")), "").strip()
    return " ".join(x for x in (make, model) if x) or None


def facts(p: Path) -> dict:
    info = ffprobe(p)
    fmt = info["format"]
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if v is None or "duration" not in fmt:
        raise ValueError("no video stream")
    created = fmt.get("tags", {}).get("creation_time")
    captured = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(timezone.utc) if created else None
    return {
        "original_name": p.name,
        "sha256": sha256(p),
        "size": p.stat().st_size,
        "mtime_ns": p.stat().st_mtime_ns,
        "captured_utc": captured.isoformat() if captured else None,
        "camera": camera(p, fmt.get("tags", {})),
        "duration": round(float(fmt["duration"]), 3),
        "fps": v.get("r_frame_rate"),
        "width": v["width"],
        "height": v["height"],
        "codec": v["codec_name"],
        "pix_fmt": v.get("pix_fmt"),
        "color_range": v.get("color_range"),
        "color_space": v.get("color_space"),
        "color_transfer": v.get("color_transfer"),
        "color_primaries": v.get("color_primaries"),
    }


def unchanged(p: Path, f: dict) -> bool:
    """Whether p still has the size and mtime its sidecar facts recorded. It never hashes, so any reader may ask;
    library.confirm settles a mismatch by hash."""
    st = p.stat()
    return st.st_size == f["size"] and st.st_mtime_ns == f.get("mtime_ns")


def assumed(f: dict) -> dict:
    """What the file doesn't say about itself (lens squeeze, log curve, gamut), from the first camera rule in the site
    config whose model prefix matches. Edit the sidecar to override one clip."""
    for rule in config.load().get("cameras", []):
        if (f["camera"] or "").startswith(rule["model_prefix"]):
            return {"squeeze": rule.get("squeeze"), "log": rule.get("log"), "gamut": rule.get("gamut"),
                    "by": f"camera rule: {rule['model_prefix']}"}
    return {"squeeze": None, "log": None, "gamut": None, "by": "no camera rule: set squeeze by hand"}
