"""Render Library clips through the grade: an OTIO timeline to a 2.39:1 master, or single stills, by one filter graph.

The timeline is the whole edit: video track 1 is picture, every audio track is mixed under it. An audio clip may set
`metadata["footage"]["lufs"]` for its loudness (dialogue -15, ambience -21). Kdenlive and Resolve open the same file.
The frame is the largest 2.39:1 picture every clip can fill without upscaling vertically: 5162x2160 for 4K 1.6x.
A clip whose media reference is a GeneratorReference of kind "title" is a title card: its `text` on black, fading in
and out, with optional `size` (share of the frame height), `font` (a fontconfig name) and `fade` (seconds).
Stills go through exactly the same picture graph, so an approved still is what the video will show.
A focus pull in a still shot is retimed so the focus eases in and out evenly over the same duration (smooth.py);
blended frames look like in-between focus. Cut points don't move.

python -m footage.render EDIT.otio
python -m footage.render --stills OUT_DIR CLIP@SECONDS ...
"""
import argparse
import subprocess
from fractions import Fraction
import tempfile
from pathlib import Path

import numpy as np
import opentimelineio as otio

from . import grade, library, sidecar, smooth

ASPECT = 2.39
FADE_IN, FADE_OUT = 0.8, 1.0
# ffmpeg-gpu (BtbN build) has 10-bit x265; Arch ARM's x265 is 8-bit only, and ffmpeg silently falls back to 8-bit.
FFMPEG = "ffmpeg-gpu"


def items(track: otio.schema.Track):
    """(clip path or None for a generated clip, source start s, duration, timeline start s, clip) for each clip."""
    for item in track:
        if isinstance(item, otio.schema.Clip):
            at = track.range_of_child(item).start_time.to_seconds()
            ref = item.media_reference
            path = Path(ref.target_url) if isinstance(ref, otio.schema.ExternalReference) else None
            yield path, item.source_range.start_time.to_seconds(), item.source_range.duration, at, item


def title(clip: otio.schema.Clip, size: tuple[int, int], rate: str, frames: int, tag: str) -> str:
    """A title card: white text centred on black, fading in and out, as 16-bit RGB at [tag]."""
    p = clip.media_reference.parameters
    w, h = size
    d, fade = frames / float(Fraction(rate)), float(p.get("fade", 1.0))
    font = subprocess.run(["fc-match", "-f", "%{file}", p.get("font", "Sans")], capture_output=True, text=True).stdout
    text = str(p["text"]).replace("\\", "\\\\").replace("'", "\u2019").replace(":", "\\:")
    alpha = f"if(lt(t,{fade}),t/{fade},if(gt(t,{d - fade:.3f}),({d:.3f}-t)/{fade},1))"
    return (f"color=c=black:s={w}x{h}:r={rate}:d={d + 1:.3f},format=yuv444p,"
            f"drawtext=fontfile='{font}':text='{text}':fontcolor=white:fontsize={round(h * float(p.get('size', 0.045)))}:"
            f"x=(w-text_w)/2:y=(h-text_h)/2:alpha='{alpha}',trim=end_frame={frames},format=gbrp16le[{tag}]")


def window(f: dict, squeeze: float) -> tuple[int, int]:
    """The centred source region, in recorded pixels, that desqueezes to 2.39:1."""
    if f["width"] * squeeze / f["height"] >= ASPECT:
        return round(f["height"] * ASPECT / squeeze / 2) * 2, f["height"]
    return f["width"], round(f["width"] * squeeze / ASPECT / 2) * 2


def frame_size(scs: list) -> tuple[int, int]:
    h = min(window(sc["facts"], sc["assumed"]["squeeze"])[1] for sc in scs)
    return round(h * ASPECT / 2) * 2, h


def retime(sc: dict, start: float, dur: float) -> str | None:
    """Filters that apply the smoothest retime of each still focus pull inside this shot, or None if there is none."""
    points = sorted(k for p in sc.get("focus", {}).get("pulls", []) if p.get("smooth")
                    and p["start"] >= start and p["end"] <= start + dur for k in p["smooth"]["knots"])
    return smooth.filters(points, start, dur, sc["facts"]["fps"]) if points else None


def picture(src: str, sc: dict, size: tuple[int, int], tmp: Path, tag: str, look: Path = grade.LOOK) -> list[str]:
    """Filter chains taking camera frames at [src] to the graded, desqueezed 16-bit RGB picture at [tag]."""
    w, h = size
    cw, ch = window(sc["facts"], sc["assumed"]["squeeze"])
    lut, halo = grade.write_luts(sc, tmp, tag, look)
    glow, decode, encode = (tmp / n for n in ("glow.cube", "decode.cube", "encode.cube"))
    if not glow.exists():
        grade.write_glow(tmp)
    # The glow is soft, so it is blurred at quarter size: a tight core and a wide skirt, then tinted and added as light.
    return [
        f"[{src}]crop={cw}:{ch},scale={w}:{h}:flags=lanczos,setsar=1,format=gbrp16le,split[{tag}p][{tag}s]",
        f"[{tag}p]lut3d=file='{lut}':interp=tetrahedral,lut1d=file='{decode}'[{tag}c]",
        f"[{tag}s]lut3d=file='{halo}',scale={w // 4}:{h // 4}:flags=area,split[{tag}h1][{tag}h2]",
        f"[{tag}h1]gblur=sigma={h * 0.004 / 4:.2f}[{tag}t]",
        f"[{tag}h2]gblur=sigma={h * 0.014 / 4:.2f}[{tag}k]",
        f"[{tag}t][{tag}k]mix=inputs=2:weights=0.6 0.4,lut1d=file='{glow}',scale={w}:{h}:flags=bicubic[{tag}g]",
        f"[{tag}c][{tag}g]blend=all_mode=addition,lut1d=file='{encode}'[{tag}]",
    ]


def render(edit: Path) -> Path:
    timeline = otio.adapters.read_from_file(str(edit))
    out = edit.with_suffix(".mp4")
    total = timeline.duration().to_seconds()
    pictures = [(p, sidecar.read(p[0]) if p[0] else None) for p in items(timeline.video_tracks()[0])]
    filmed = [sc for _, sc in pictures if sc]
    size, rate = frame_size(filmed), filmed[0]["facts"]["fps"]
    cmd, graph, inputs = [FFMPEG, "-v", "error", "-stats", "-y"], [], 0
    with tempfile.TemporaryDirectory() as tmp:
        for i, ((clip, start, dur, _, item), sc) in enumerate(pictures):
            n = round(dur.to_frames())
            if sc is None:
                graph.append(title(item, size, rate, n, f"v{i}"))
                continue
            # Two decoder threads per input: sixteen 4K inputs at the default thread count would hold many GB of frames.
            cmd += ["-threads", "2", "-ss", f"{start:.3f}", "-t", f"{dur.to_seconds() + 1:.3f}", "-i", str(clip)]
            eased = retime(sc, start, dur.to_seconds()) or ""
            graph.append(f"[{inputs}:v]trim=end_frame={n},setpts=PTS-STARTPTS,{eased}tpad=stop_mode=clone:stop=2,trim=end_frame={n}[s{i}]")
            graph += picture(f"s{i}", sc, size, Path(tmp), f"v{i}")
            inputs += 1
        # The camera's full-range flag must not reach the master: players expect standard (limited) range.
        graph.append("".join(f"[v{i}]" for i in range(len(pictures))) + f"concat=n={len(pictures)}:v=1:a=0,"
                     f"fade=t=in:d={FADE_IN},fade=t=out:st={total - FADE_OUT:.3f}:d={FADE_OUT},"
                     f"scale=out_color_matrix=bt709:out_range=limited,format=yuv420p10le[v]")
        mix = []
        for track in timeline.audio_tracks():
            for clip, start, dur, at, item in items(track):
                cmd += ["-ss", f"{start:.3f}", "-t", f"{dur.to_seconds():.3f}", "-i", str(clip)]
                d = dur.to_seconds()
                graph.append(f"[{inputs}:a]loudnorm=I={item.metadata.get('footage', {}).get('lufs', -20)}:TP=-2,aresample=48000,"
                             f"afade=t=in:d=0.08,afade=t=out:st={max(d - 0.08, 0):.3f}:d=0.08,"
                             f"adelay={round(at * 1000)}:all=1[m{len(mix)}]")
                mix.append(inputs)
                inputs += 1
        maps = ["-map", "[v]"]
        if mix:
            graph.append("".join(f"[m{k}]" for k in range(len(mix))) + f"amix=inputs={len(mix)}:normalize=0:duration=longest,"
                         f"atrim=0:{total:.3f},afade=t=out:st={total - FADE_OUT:.3f}:d={FADE_OUT}[a]")
            maps += ["-map", "[a]", "-c:a", "aac", "-b:a", "256k"]
        cmd += ["-filter_complex", ";".join(graph), *maps,
                "-c:v", "libx265", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p10le", "-tag:v", "hvc1",
                "-x265-params", "colorprim=bt709:transfer=bt709:colormatrix=bt709:log-level=error",
                "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv",
                "-write_tmcd", "0", "-movflags", "+faststart", str(out)]
        print(f"  {len(pictures)} shots at {size[0]}x{size[1]}", flush=True)
        subprocess.run(cmd, check=True)
    return out


def still(clip: Path, t: float, out: Path, look: Path = grade.LOOK) -> Path:
    """One graded frame at the master's full size, as a maximum-quality JPEG."""
    sc = sidecar.read(clip)
    with tempfile.TemporaryDirectory() as tmp:
        graph = picture("0:v", sc, frame_size([sc]), Path(tmp), "x", look) + ["[x]format=rgb24[o]"]
        subprocess.run([FFMPEG, "-v", "error", "-y", "-threads", "4", "-ss", f"{t:.3f}", "-i", str(clip),
                        "-filter_complex", ";".join(graph), "-map", "[o]", "-frames:v", "1",
                        "-pix_fmt", "yuvj444p", "-q:v", "1", str(out)], check=True)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="footage.render")
    ap.add_argument("edit", nargs="?", type=Path)
    ap.add_argument("--stills", type=Path, help="write stills of CLIP@SECONDS into this folder")
    ap.add_argument("frames", nargs="*")
    a = ap.parse_args()
    if a.stills:
        lib = {p.stem: p for p in library.clips(Path.home() / "Videos/Library")}
        for spec in ([str(a.edit)] if a.edit else []) + a.frames:
            name, t = spec.split("@")
            print(still(lib[name], float(t), a.stills / f"{name}.jpg"))
    else:
        print(render(a.edit))
