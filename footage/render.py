"""Render Library clips through the grade: an OTIO timeline to a 2.39:1 master, or single stills, by one filter graph.

The timeline is the whole edit: video track 1 is picture, every audio track is mixed under it. An audio clip may set
`metadata["footage"]["lufs"]` for its loudness (dialogue -15, ambience -21). Kdenlive and Resolve open the same file.
The frame is the largest 2.39:1 picture every clip can fill without upscaling vertically: 5162x2160 for 4K 1.6x.
Stills go through exactly the same picture graph, so an approved still is what the video will show.
A focus pull in a still shot (nothing else moving) is retimed so the focus eases in and out evenly over the same
duration; neighbouring frames are blended, which for a pull looks like an in-between focus. Cut points don't move.

python -m footage.render EDIT.otio
python -m footage.render --stills OUT_DIR CLIP@SECONDS ...
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import opentimelineio as otio

from . import grade, library, sidecar

ASPECT = 2.39
FADE_OUT = 1.0
SMOOTH_MOTION, SMOOTH_PAN = 0.35, 0.08  # a pull is smoothed only in a still shot: no subject motion, no pan
# ffmpeg-gpu (BtbN build) has 10-bit x265; Arch ARM's x265 is 8-bit only, and ffmpeg silently falls back to 8-bit.
FFMPEG = "ffmpeg-gpu"


def items(track: otio.schema.Track):
    """(clip path, source start s, duration, timeline start s, metadata) for each clip on a track."""
    for item in track:
        if isinstance(item, otio.schema.Clip):
            at = track.range_of_child(item).start_time.to_seconds()
            yield Path(item.media_reference.target_url), item.source_range.start_time.to_seconds(), item.source_range.duration, at, item.metadata


def window(f: dict, squeeze: float) -> tuple[int, int]:
    """The centred source region, in recorded pixels, that desqueezes to 2.39:1."""
    if f["width"] * squeeze / f["height"] >= ASPECT:
        return round(f["height"] * ASPECT / squeeze / 2) * 2, f["height"]
    return f["width"], round(f["width"] * squeeze / ASPECT / 2) * 2


def frame_size(scs: list) -> tuple[int, int]:
    h = min(window(sc["facts"], sc["assumed"]["squeeze"])[1] for sc in scs)
    return round(h * ASPECT / 2) * 2, h


def ease(x):
    return x * x * (3 - 2 * x)


def retime(sc: dict, start: float, dur: float) -> str | None:
    """Filters that ease each still focus pull inside this shot [start, start + dur], or None if there is none."""
    knots = [(0.0, 0.0)]
    grid = np.linspace(0, 1, 2001)
    for p in sc.get("focus", {}).get("pulls", []):
        if p["motion"] > SMOOTH_MOTION or p["pan"] > SMOOTH_PAN or p["start"] < start or p["end"] > start + dur:
            continue
        t, c = np.unique([pt[0] for pt in p["curve"]], return_index=True)
        c = np.maximum.accumulate(np.array([pt[1] for pt in p["curve"]])[c])
        c = (c - c[0]) / max(c[-1] - c[0], 1e-9)
        # How far the focus had travelled at each source frame; a little of plain time keeps it strictly increasing,
        # so a pause in the pull still takes some time instead of none.
        travel = 0.9 * c + 0.1 * (t - t[0]) / (t[-1] - t[0])
        u = t[0] + (t[-1] - t[0]) * np.interp(travel, ease(grid), grid)  # when that much travel happens, eased
        knots += [(a - start, b - start) for a, b in zip(t, u) if knots[-1][0] < a - start]
    if len(knots) == 1:
        return None
    if knots[-1][0] < dur:
        knots.append((dur, dur))
    expr = None
    for (t0, u0), (t1, u1) in reversed(list(zip(knots, knots[1:]))):
        seg = f"{u0:.5f}+(T-{t0:.5f})*{(u1 - u0) / (t1 - t0):.6f}"
        expr = seg if expr is None else f"if(lt(T,{t1:.5f}),{seg},{expr})"
    rate = sc["facts"]["fps"]
    return f"setpts='({expr})/TB',framerate=fps={rate}:interp_start=0:interp_end=255:scene=100,"


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
    shots = [(p, sidecar.read(p[0])) for p in items(timeline.video_tracks()[0])]
    size = frame_size([sc for _, sc in shots])
    cmd, graph = [FFMPEG, "-v", "error", "-stats", "-y"], []
    with tempfile.TemporaryDirectory() as tmp:
        for i, ((clip, start, dur, _, _), sc) in enumerate(shots):
            # Two decoder threads per input: sixteen 4K inputs at the default thread count would hold many GB of frames.
            cmd += ["-threads", "2", "-ss", f"{start:.3f}", "-t", f"{dur.to_seconds() + 1:.3f}", "-i", str(clip)]
            n = round(dur.to_frames())
            eased = retime(sc, start, dur.to_seconds()) or ""
            graph.append(f"[{i}:v]trim=end_frame={n},setpts=PTS-STARTPTS,{eased}tpad=stop_mode=clone:stop=2,trim=end_frame={n}[s{i}]")
            graph += picture(f"s{i}", sc, size, Path(tmp), f"v{i}")
        # The camera's full-range flag must not reach the master: players expect standard (limited) range.
        graph.append("".join(f"[v{i}]" for i in range(len(shots))) + f"concat=n={len(shots)}:v=1:a=0,"
                     f"fade=t=out:st={total - FADE_OUT:.3f}:d={FADE_OUT},"
                     f"scale=out_color_matrix=bt709:out_range=limited,format=yuv420p10le[v]")
        mix = []
        for track in timeline.audio_tracks():
            for clip, start, dur, at, meta in items(track):
                n = len(shots) + len(mix)
                cmd += ["-ss", f"{start:.3f}", "-t", f"{dur.to_seconds():.3f}", "-i", str(clip)]
                d = dur.to_seconds()
                graph.append(f"[{n}:a]loudnorm=I={meta.get('footage', {}).get('lufs', -20)}:TP=-2,aresample=48000,"
                             f"afade=t=in:d=0.08,afade=t=out:st={max(d - 0.08, 0):.3f}:d=0.08,"
                             f"adelay={round(at * 1000)}:all=1[m{len(mix)}]")
                mix.append(n)
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
        print(f"  {len(shots)} shots at {size[0]}x{size[1]}", flush=True)
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
