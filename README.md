# Azimuth Video

Azimuth Video is a local, agent-friendly toolkit for camera footage. It files clips, describes and measures them,
and renders graded edits. All the models run on your own machine.

Each clip gets one JSON sidecar next to it. The sidecar holds everything the toolkit knows about the clip. Search,
selects and timelines read these sidecars, so an AI agent can find shots and build edits from them.

## What it does

1. **File.** It moves finished clips from an inbox into one folder per shooting day. It never overwrites a file,
   and it leaves duplicates in the inbox.
2. **Describe.** A local vision model writes a summary, tags, shot size, camera movement and usable moments for each clip.
3. **Transcribe.** Parakeet transcribes the speech, and a diarizer labels the speakers.
4. **Measure.** It measures exposure, white balance, clipping, sharpness and motion. It also finds faces and measures how they are lit.
5. **Find focus pulls.** It tracks sharpness across the frame on every frame. It records each rack focus, when it starts and when it settles.
6. **Recognize people.** It groups faces into people across the whole library. You can add names to `people.json`.
7. **Grade and render.** It renders an OpenTimelineIO timeline, or single stills, through one picture graph:
   - each shot gets its own exposure and white-balance correction;
   - every shot gets the same film look, a spektrafilm simulation of Kodak Vision3 250D printed on Kodak 2393;
   - halation glows around light sources.

   The master is 10-bit HEVC at the largest 2.39:1 frame the footage supports (5162x2160 for 4K 1.6x anamorphic).

Kdenlive and DaVinci Resolve open the same timeline files. A timeline can also hold title cards (an OTIO
GeneratorReference of kind `title`) and music, and `python -m footage.music TRACK` finds a track's beats and
loudness so cuts can land on the beat.

## Use

```bash
python -m footage                     # file the inbox, then fill every sidecar section that is missing or out of date
python -m footage.render EDIT.otio    # render a timeline to EDIT.mp4
python -m footage.render --stills OUT_DIR CLIP@SECONDS ...   # full-resolution graded stills
bash acceptance.sh                    # filing safety checks on a sandbox of hard links
```

The defaults are `~/Videos/Ingest` for the inbox and `~/Videos/Library` for the library.

## Requirements

This toolkit was built and tested on an ARM64 Linux laptop with an NVIDIA RTX Spark GPU.

- Python 3.12 with numpy, scipy, colour-science, opentimelineio, opencv-python-headless, onnx-asr and sherpa-onnx.
- `ffmpeg` and `ffprobe`, plus `ffmpeg-gpu`: an FFmpeg build with NVDEC and 10-bit x265 (for example, a BtbN build).
- LM Studio, serving `qwen/qwen3.5-35b-a3b`, for the descriptions.
- Models in `~/.local/share/footage/models`: YuNet and SFace (OpenCV Zoo), the pyannote segmentation model and NeMo TitaNet (sherpa-onnx).
- Parakeet TDT 0.6B v2 in voxtype's model folder.

## Site settings

Settings for your own footage live outside the repository, in `~/.config/azimuth-video/config.json`
(or the path in `AZIMUTH_VIDEO_CONFIG`). Every key is optional:

```json
{
  "context": "One sentence about what the footage shows, given to the description model.",
  "timezone": "Area/City",
  "cameras": [{"model_prefix": "Canon EOS", "squeeze": 1.6, "log": "Canon Log 3", "gamut": "Cinema Gamut"}]
}
```

- Without a timezone, shooting days follow the system's local time.
- Without a matching camera rule, a clip's squeeze is unknown. Set it in the `assumed` section of that clip's sidecar.
- People's names and skin levels live in `people.json` in your library. They never go in this repository.

Your library (clips, sidecars, `people.json`) and your renders stay on your machine. Keep them out of this repository.

## Credits

The film look uses LUTs baked with [spektrafilm](https://github.com/andreavolpato/spektrafilm) (film modeling
powered by spektrafilm). The LUTs are CC BY-SA 4.0. See `looks/`.
