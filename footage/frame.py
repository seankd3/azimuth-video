"""python -m footage.frame CLIP SECONDS [--out PATH]: one frame of any clip, desqueezed, as a JPEG.

For looking up what a transcript's timestamp shows. A filed clip reads its sidecar (its squeeze, and a RAW clip's
developed picture); any other video, such as one still on the card, takes its squeeze from the camera rules, as filing
would. The picture is the camera's own (flat log), not the grade: python -m footage.render --stills is the graded one.

    python -m footage.frame /run/media/sean/EOS_DIGITAL/DCIM/100EAKSS/SKDA0909.MP4 125.5 --out cut-02:05.jpg
"""
import argparse
import subprocess
from pathlib import Path

from . import develop, idle, probe, sidecar, view

WIDTH = 1600


def facts(clip: Path) -> dict:
    """A clip's sidecar, or for a clip with none what view needs from it, read from the file without hashing it."""
    sc = sidecar.read(clip)
    if sc is not None:
        return sc
    info = probe.ffprobe(clip)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    f = {"original_name": clip.name, "width": v["width"], "height": v["height"],
         "camera": probe.camera(clip, info["format"].get("tags", {}))}
    if develop.raw({"facts": f}):
        raise SystemExit(f"{clip.name} is RAW: file it with python -m footage, which develops it, then ask again")
    return {"facts": f, "assumed": probe.assumed(f)}


def jpeg(clip: Path, sc: dict, t: float, width: int = WIDTH) -> bytes:
    """The whole desqueezed frame at t seconds, `width` pixels wide."""
    return subprocess.run(["ffmpeg", "-v", "error", "-threads", "1", "-ss", f"{t:.2f}", "-i", view.source(clip, sc),
                           "-frames:v", "1", "-vf", f"{view.cpu(sc, width)},setsar=1", "-q:v", "4",
                           "-f", "image2pipe", "-c:v", "mjpeg", "-"], capture_output=True, check=True).stdout


def seconds(text: str) -> float:
    """SECONDS as 125.5, or as a transcript's 02:05 or 1:02:05."""
    t = 0.0
    for part in text.split(":"):
        t = t * 60 + float(part)
    return t


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="footage.frame")
    ap.add_argument("clip", type=Path)
    ap.add_argument("seconds", type=seconds, help="125.5, 02:05 or 1:02:05")
    ap.add_argument("--out", type=Path, help="default: CLIP's name and the time, in the current folder")
    ap.add_argument("--width", type=int, default=WIDTH)
    a = ap.parse_args()
    idle()
    out = a.out or Path(f"{a.clip.stem}-{a.seconds:.2f}.jpg")
    data = jpeg(a.clip, facts(a.clip), a.seconds, a.width)
    if not data:
        raise SystemExit(f"no frame at {a.seconds:.2f} s: the clip is shorter")
    out.write_bytes(data)
    print(out)
