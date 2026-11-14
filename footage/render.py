"""Render Library clips through the grade: an OTIO timeline to a 2.39:1 master, or single stills, by one picture path.

The timeline is the whole edit: video track 1 is picture, every audio track is mixed under it. The edit fades in from
black and out to black over `metadata["footage"]["fades"]` seconds ([in, out], default [0.8, 1.0]; 0 is a cut). The
whole edit is printed in one look (grade.py): the timeline's `metadata["footage"]["look"]`, or `--look`, or the default; the master
is written beside the timeline as "EDIT - LOOK.mp4", so one edit can be rendered in several looks. An audio clip may set
`metadata["footage"]["lufs"]` for its loudness (dialogue -15, ambience -21).
The master's aspect is the timeline's `metadata["footage"]["aspect"]`: a number (2.39 unless it says), or "full" for
the first shot's whole recorded frame, desqueezed. Its size is the largest frame of that aspect every clip can fill
unframed without upscaling vertically: 5162x2160 at 2.39 for 4K 1.6x. Each clip shows its window of the frame
(view.py): its `metadata["footage"]["framing"]` turns it in quarter turns, moves the window and pushes in. A timeline
may set `["height"]` for a smaller master, and `["crf"]` (the encoder's quantizer, default 18) for a smaller file: a
documentation copy is {"look": "natural", "aspect": "full", "height": 1080, "crf": 30, "fades": [0, 0]}.
A clip whose media reference is a GeneratorReference of kind "title" is a title card: its `text` on black, fading in
and out, with optional `size` (share of the frame height), `font` (a fontconfig name) and `fade` (seconds).

Every frame goes through picture.py on the GPU, shot after shot, into one encoder: the GPU's HEVC encoder, reached
through Vulkan video (the NVENC interface refuses this driver). So a render holds a few frames at a time however long
the edit is. Stills go through exactly the same picture path, so an approved still is what the video will show.
A focus pull in a still shot is retimed so the focus eases in and out evenly over the same duration (smooth.py);
blended frames look like in-between focus. Cut points don't move. Shots are shown as shot: nothing is stabilized.

python -m footage.render EDIT.otio [--look NAME,NAME...]
python -m footage.render --stills OUT_DIR [--look NAME,NAME...] CLIP@SECONDS ...
"""
import argparse
import queue
import subprocess
import threading
from fractions import Fraction
from pathlib import Path

import opentimelineio as otio

from . import develop, grade, idle, library, passes, people, picture, sidecar, smooth, view

FADE_IN, FADE_OUT = 0.8, 1.0
QP = 18  # the encoder's constant quantizer: 18 is visually lossless on graded 5K footage
READS = ("measured", "focus")  # the grade reads measured; a focus pull's retime reads focus, which a still never shows
FFMPEG = "ffmpeg-gpu"  # a BtbN build: NVDEC, Vulkan video and 10-bit HEVC


def read(clip: Path, needs: tuple = READS) -> dict:
    """A clip's sidecar with its person (people.of). A render from anything out of date would not be the approved
    picture, so it stops instead."""
    sc = sidecar.read(clip)
    if sc is None:
        raise SystemExit(f"{clip.name} has no sidecar: run python -m footage first")
    sc = passes.fresh(clip, sc)[0]
    missing = [s for s in needs if s not in sc]
    if missing:
        raise SystemExit(f"{clip.name}: {', '.join(missing)} missing or out of date: run python -m footage first")
    return {**sc, "person": people.of(clip, sc)}


def items(track: otio.schema.Track):
    """(clip path or None for a generated clip, source start s, duration, timeline start s, clip) for each clip."""
    for item in track:
        if isinstance(item, otio.schema.Clip):
            at = track.range_of_child(item).start_time.to_seconds()
            ref = item.media_reference
            path = Path(ref.target_url) if isinstance(ref, otio.schema.ExternalReference) else None
            yield path, item.source_range.start_time.to_seconds(), item.source_range.duration, at, item


def title(clip: otio.schema.Clip, size: tuple[int, int], rate: str, frames: int) -> list[str]:
    """A title card: white text centred on black, fading in and out: an ffmpeg command writing it as 16-bit RGB."""
    p = clip.media_reference.parameters
    w, h = size
    d, fade = frames / float(Fraction(rate)), float(p.get("fade", 1.0))
    font = subprocess.run(["fc-match", "-f", "%{file}", p.get("font", "Sans")], capture_output=True, text=True).stdout
    text = str(p["text"]).replace("\\", "\\\\").replace("'", "\u2019").replace(":", "\\:")
    alpha = f"if(lt(t,{fade}),t/{fade},if(gt(t,{d - fade:.3f}),({d:.3f}-t)/{fade},1))"
    graph = (f"color=c=black:s={w}x{h}:r={rate}:d={d + 1:.3f},format=yuv444p,"
            f"drawtext=fontfile='{font}':text='{text}':fontcolor=white:fontsize={round(h * float(p.get('size', 0.045)))}:"
            f"x=(w-text_w)/2:y=(h-text_h)/2:alpha='{alpha}',trim=end_frame={frames},format=gbrp16le")
    return [FFMPEG, "-v", "error", "-f", "lavfi", "-i", graph, "-frames:v", str(frames), "-f", "rawvideo", "-"]


def retime(sc: dict, start: float, dur: float) -> str | None:
    """Filters that apply the smoothest retime of each still focus pull inside this shot, or None if there is none."""
    points = sorted(k for p in sc.get("focus", {}).get("pulls", []) if p.get("smooth")
                    and p["start"] >= start and p["end"] <= start + dur for k in p["smooth"]["knots"])
    return smooth.filters(points, start, dur, sc["facts"]["fps"]) if points else None


def decode(clip: Path, sc: dict, start: float, frames: int, eased: str = "", win: view.Window | None = None):
    """A shot's frames in recorded pixels, cropped to its window (view.window) and turned, as RGB code values on the
    GPU (picture.frames). ffmpeg hands them over in the file's own YUV, unconverted. The GPU decodes a camera clip
    (NVDEC); a developed RAW picture (8K 4:4:4) is decoded on the CPU."""
    x, y, cw, ch, turn = win or view.window(sc)
    fps = float(Fraction(sc["facts"]["fps"]))
    fmt, full_range = ("yuv444p12le", True) if develop.raw(sc) else (sc["facts"]["pix_fmt"], sc["facts"]["color_range"] == "pc")
    cmd = [FFMPEG, "-v", "error", *([] if develop.raw(sc) else ["-hwaccel", "cuda"]), "-threads", "8",
           "-ss", f"{start:.3f}", "-t", f"{frames / fps + 1:.3f}", "-i", view.source(clip, sc),
           "-vf", f"trim=end_frame={frames},setpts=PTS-STARTPTS,{eased}crop={cw}:{ch}:{x}:{y},"
                  f"tpad=stop_mode=clone:stop=2,trim=end_frame={frames}",
           "-pix_fmt", fmt, "-frames:v", str(frames), "-f", "rawvideo", "-"]
    pictures = picture.frames(cmd, (cw, ch), fmt, full_range)
    return (f.rot90(-turn, (1, 2)) for f in pictures) if turn else pictures


def encoder(timeline: otio.schema.Timeline, size: tuple[int, int], rate: str, total: float, fade_out: float,
            qp: int, out: Path) -> subprocess.Popen:
    """The one encoder of a render: 10-bit frames on stdin to HEVC on the GPU, with the timeline's sound mixed in."""
    w, h = size
    cmd, graph, mix = [FFMPEG, "-v", "error", "-y", "-init_hw_device", "vulkan=gpu", "-filter_hw_device", "gpu",
                       "-f", "rawvideo", "-pix_fmt", "p010le", "-s", f"{w}x{h}", "-r", rate, "-i", "-"], ["[0:v]setparams=range=tv:colorspace=bt709:color_primaries=bt709:color_trc=bt709,hwupload[v]"], []
    for track in timeline.audio_tracks():
        for clip, start, dur, at, item in items(track):
            cmd += ["-ss", f"{start:.3f}", "-t", f"{dur.to_seconds():.3f}", "-i", str(clip)]
            d = dur.to_seconds()
            graph.append(f"[{len(mix) + 1}:a]loudnorm=I={item.metadata.get('footage', {}).get('lufs', -20)}:TP=-2,aresample=48000,"
                         f"afade=t=in:d=0.08,afade=t=out:st={max(d - 0.08, 0):.3f}:d=0.08,"
                         f"adelay={round(at * 1000)}:all=1[m{len(mix)}]")
            mix.append(len(mix) + 1)
    maps = ["-map", "[v]"]
    if mix:
        graph.append("".join(f"[m{k}]" for k in range(len(mix))) + f"amix=inputs={len(mix)}:normalize=0:duration=longest,"
                     f"atrim=0:{total:.3f}" + (f",afade=t=out:st={total - fade_out:.3f}:d={fade_out}" if fade_out else "") + "[a]")
        maps += ["-map", "[a]", "-c:a", "aac", "-b:a", "256k"]
    return subprocess.Popen([*cmd, "-filter_complex", ";".join(graph), *maps, "-c:v", "hevc_vulkan", "-profile:v", "main10",
                             "-rc_mode", "cqp", "-qp", str(qp), "-tag:v", "hvc1", "-write_tmcd", "0",
                             "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)


def render(edit: Path, name: str | None = None) -> Path:
    timeline = otio.adapters.read_from_file(str(edit))
    settings = timeline.metadata.get("footage", {})
    look = grade.look(name or settings.get("look", grade.DEFAULT))
    fade_in, fade_out = settings.get("fades", (FADE_IN, FADE_OUT))
    master = edit.with_name(f"{edit.stem} - {look.name}.mp4")
    part = master.with_suffix(".part.mp4")
    total = timeline.duration().to_seconds()
    pictures = [(p, read(p[0]) if p[0] else None) for p in items(timeline.video_tracks()[0])]
    filmed = [sc for _, sc in pictures if sc]
    aspect = view.aspect(settings.get("aspect", view.ASPECT), filmed)
    h = settings.get("height") or view.master(filmed, aspect)[1]
    size = (round(h * aspect / 2) * 2, h)
    rate = filmed[0]["facts"]["fps"]
    fps = float(Fraction(rate))
    print(f"  {len(pictures)} shots at {size[0]}x{size[1]} in {look.name}", flush=True)
    enc = encoder(timeline, size, rate, total, fade_out, settings.get("crf", QP), part)
    out, done, encoded = queue.Queue(picture.AHEAD), 0, picture.Encoded()
    failed: list = []

    def feed():  # the encoder is fed from its own thread, so writing a frame overlaps grading the next
        while (f := out.get()) is not None:
            try:
                failed or enc.stdin.write(f)
            except OSError as e:  # the encoder stopped: keep taking frames so the render can end and report it
                failed.append(e)
    writer = threading.Thread(target=feed, daemon=True)
    writer.start()
    for (clip, start, dur, at, item), sc in pictures:
        n = round(dur.to_frames())
        if sc is None:
            source, grading = picture.frames(title(item, size, rate, n), size, "gbrp16le", True), None
        else:
            eased = retime(sc, start, dur.to_seconds()) or ""
            if eased:
                print(f"  {clip.stem}: retimed focus pull", flush=True)
            win = view.window(sc, item.metadata.get("footage", {}).get("framing"), aspect)
            source, grading = decode(clip, sc, start, n, eased, win), picture.shot(sc, look, size, win.turn)
        for frame in source:
            t = done / fps
            fade = min(1.0, t / fade_in if fade_in else 1.0, (total - t) / fade_out if fade_out else 1.0)
            out.put(encoded((grading(frame) if grading else frame) * max(fade, 0.0)))
            done += 1
        print(f"  {clip.stem if clip else 'title'}: {done} frames", flush=True)
    out.put(None)
    writer.join()
    if not failed:
        enc.stdin.close()
    if enc.wait():
        raise subprocess.CalledProcessError(enc.returncode, FFMPEG)
    part.rename(master)  # a render that stops leaves its part, never a short master under the master's name
    return master


def still(clip: Path, t: float, out: Path, look: grade.Look) -> Path:
    """One graded frame at the master's full size, as a maximum-quality JPEG."""
    import cv2
    sc = read(clip, ("measured",))
    if not 0 <= t < sc["facts"]["duration"]:  # past the end ffmpeg writes nothing
        raise SystemExit(f"{clip.name} is {sc['facts']['duration']:.1f} s long: no frame at {t:g} s")
    size = view.master([sc])
    rgb = picture.shot(sc, look, size)(next(decode(clip, sc, t, 1)))
    bgr = (rgb[[2, 1, 0]].permute(1, 2, 0) * 255).round().byte().cpu().numpy()
    cv2.imwrite(str(out), bgr, [cv2.IMWRITE_JPEG_QUALITY, 100, cv2.IMWRITE_JPEG_SAMPLING_FACTOR, cv2.IMWRITE_JPEG_SAMPLING_FACTOR_444])
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="footage.render")
    ap.add_argument("edit", nargs="?", type=Path)
    ap.add_argument("--stills", type=Path, help="write stills of CLIP@SECONDS into this folder")
    ap.add_argument("frames", nargs="*")
    ap.add_argument("--look", help="comma-separated looks (python -m footage.grade lists them); one output each")
    a = ap.parse_args()
    idle()
    names = a.look.split(",") if a.look else [None]
    if a.stills:
        lib = {p.stem: p for p in library.clips(Path.home() / "Videos/Library")}
        for spec in ([str(a.edit)] if a.edit else []) + a.frames:
            clip, t = spec.split("@")
            for look in (grade.look(n or grade.DEFAULT) for n in names):
                print(still(lib[clip], float(t), a.stills / f"{clip}-{look.name}.jpg", look))
    else:
        for name in names:
            print(render(a.edit, name))
