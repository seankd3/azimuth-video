"""Measured facts about one media file, and whether a copy into the inbox has finished."""
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import config

VIDEO = {".mp4", ".mov", ".crm"}  # .crm: Canon Cinema RAW Light, read through develop.py
# A camera writes its own notes (lens, log, how it was held) at the front of a clip: in every Canon clip read so far,
# MP4 and an 8K RAW of 107 GB alike, they sat in the first 8 MB, so a clip is never read whole to learn them.
HEAD = 8 << 20
LOGS = {0: None, 1: "Canon Log", 2: "Canon Log 2", 3: "Canon Log 3"}  # the camera's CanonLogVersion: 0 is log off


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


def notes(p: Path) -> dict:
    """What the camera's own notes in the file say about the shot, None where they say nothing. lens: the lens's name,
    "" when no electronic lens was on the camera; canon_log: the CanonLogVersion recorded; roll: degrees the camera was
    rolled about its lens, as its level sensor read it; iso, exposure_time (s) and f_number: the exposure as set (a
    manual lens's aperture is unknown to the camera); measured_ev: the light the camera's meter read."""
    with open(p, "rb") as f:
        head = f.read(HEAD)
        os.posix_fadvise(f.fileno(), 0, len(head), os.POSIX_FADV_DONTNEED)
    names = {"lens": "LensModel", "canon_log": "CanonLogVersion", "roll": "RollAngle", "iso": "ISO",
             "exposure_time": "ExposureTime", "f_number": "FNumber", "measured_ev": "MeasuredEV"}
    out = subprocess.run(["exiftool", "-j", "-n", *(f"-{t}" for t in names.values()), "-"], input=head,
                         capture_output=True, check=True).stdout
    tags = json.loads(out)[0]

    def told(k: str):
        v = tags.get(names[k])
        if k in ("iso", "exposure_time", "f_number"):  # an exposure the camera left to itself reads "undef" or 0
            return v if isinstance(v, (int, float)) and v > 0 else None
        return None if v == "undef" else v
    return {k: told(k) for k in names}


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
        "codec": v.get("codec_name") or v.get("codec_tag_string"),  # a RAW codec ffmpeg can't decode has only its tag
        "pix_fmt": v.get("pix_fmt"),
        "color_range": v.get("color_range"),
        "color_space": v.get("color_space"),
        "color_transfer": v.get("color_transfer"),
        "color_primaries": v.get("color_primaries"),
        "notes": notes(p),
    }


def unchanged(p: Path, f: dict) -> bool:
    """Whether p still has the size and mtime its sidecar facts recorded. It never hashes, so any reader may ask;
    library.confirm settles a mismatch by hash."""
    st = p.stat()
    return st.st_size == f["size"] and st.st_mtime_ns == f.get("mtime_ns")


def assumed(f: dict) -> dict:
    """What the toolkit takes the clip to be: lens squeeze, log curve and gamut. The file's own notes come first; a camera
    rule in the site config (the first whose model prefix matches) fills only what the file doesn't say. `by` names
    the source of each. Edit the sidecar (python -m footage.assume) to override one clip.

    A named lens is an electronic one, and every anamorphic lens in use is manual, so a named lens is spherical. No
    log recorded (CanonLogVersion 0) is the camera's Rec.709 video, which has no separate gamut."""
    n = f.get("notes") or {}
    rule = next((r for r in config.load().get("cameras", []) if (f["camera"] or "").startswith(r["model_prefix"])), None)
    ruled = f"camera rule: {rule['model_prefix']}" if rule else "no camera rule"
    rule = rule or {}
    if n.get("canon_log") in LOGS:
        log, log_by = LOGS[n["canon_log"]], f"file: CanonLogVersion {n['canon_log']}"
    else:
        log, log_by = rule.get("log"), ruled
    if n.get("lens"):
        squeeze, squeeze_by = 1.0, f"file: lens {n['lens']}"
    else:
        squeeze, squeeze_by = rule.get("squeeze"), ruled
    if squeeze is None:
        squeeze_by += ": set squeeze with python -m footage.assume"
    gamut, gamut_by = (rule.get("gamut"), ruled) if log else (None, log_by)
    return {"squeeze": squeeze, "log": log, "gamut": gamut, "by": {"squeeze": squeeze_by, "log": log_by, "gamut": gamut_by}}
