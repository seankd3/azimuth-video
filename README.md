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
7. **Measure shake.** It follows the camera's motion on every frame and records, second by second, how much the
   camera shakes beyond its smoothed path. Moving hands and people in front of a locked-off camera don't count.
8. **Grade and render.** It renders an OpenTimelineIO timeline, or single stills, through one picture graph:
   - each shot gets its own exposure and white-balance correction;
   - the whole edit is printed in one look you choose: a spektrafilm film-stock simulation, how hard it is printed,
     its warmth, halation around light sources, and lens vignette;
   - the looks are files in `looks/`: `cinema` (the default), `classic`, `cinestill-800t`, `kodak-gold-200`,
     `portra-400`, `fuji-pro-400h` and `fuji-superia-400`, with stronger versions of CineStill and Gold.
     `python -m footage.grade` lists them;
   - a handheld shot is stabilized: the 2.39:1 window follows the shake inside the wider desqueezed frame, with at
     most a 6% zoom, so the deliberate move stays and the picture keeps its 16-bit precision.

   The master is 10-bit HEVC at the largest 2.39:1 frame the footage supports (5162x2160 for 4K 1.6x anamorphic).

Kdenlive and DaVinci Resolve open the same timeline files. A timeline can also hold title cards (an OTIO
GeneratorReference of kind `title`) and music, and `python -m footage.music TRACK` finds a track's beats and
loudness so cuts can land on the beat.

## Use

```bash
python -m footage                     # file the inbox, then fill every sidecar section that is missing or out of date
python -m footage.find hands --size close-up --steady   # find shots; each line shows its steady stretches and focus pulls
python -m footage.render EDIT.otio [--look cinema,kodak-gold-200]   # render a timeline to "EDIT - LOOK.mp4"
python -m footage.render --stills OUT_DIR [--look ...] CLIP@SECONDS ...   # full-resolution graded stills
bash acceptance.sh                    # filing safety checks on a sandbox of hard links
```

The defaults are `~/Videos/Ingest` for the inbox and `~/Videos/Library` for the library. A layout that stays tidy:

- `~/Videos/Ingest/`: the inbox. Copy from the card here.
- `~/Videos/Library/`: raw footage, one folder per shooting day. Timelines point into it, so keep its name.
- `~/Videos/Edits/<date> <name>/`: finished edits. The timeline, its renders ("EDIT - LOOK.mp4"), and its stills.
- `~/Videos/Toolkit tests/<topic>/`: experiments, comparisons and before/after tests. A timeline picks its look
with `metadata["footage"]["look"]`; `--look` overrides it. Runs and renders use idle CPU and disk priority, so they
take only what the desktop leaves.

## Requirements

This toolkit was built and tested on an ARM64 Linux laptop with an NVIDIA RTX Spark GPU.

- Python 3.12 with numpy, scipy, colour-science, opentimelineio, opencv-python-headless, onnx-asr and sherpa-onnx.
- `ffmpeg` and `ffprobe`, plus `ffmpeg-gpu`: an FFmpeg build with NVDEC and 10-bit x265 (for example, a BtbN build).
- LM Studio, serving `qwen/qwen3.5-35b-a3b`, for the descriptions.
- Models in `~/.local/share/footage/models`: YuNet and SFace (OpenCV Zoo), the pyannote segmentation model and NeMo TitaNet (sherpa-onnx).
- Parakeet TDT 0.6B v2 in voxtype's model folder.
- Optional: [Gyroflow](https://github.com/gyroflow/gyroflow) for shots that shake too much for the built-in
  stabilizer. Since 1.7 it can measure motion from the picture alone (`--optical-correction 100`), and it corrects
  rolling shutter. For anamorphic footage, give it a lens profile with the squeeze as `input_horizontal_stretch`.
  Its output (ProRes 422 HQ, 10-bit, the source's size and timing) can replace the clip in a timeline.

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
- White balance trusts the camera's own balance and corrects only what the frame's near-grey surfaces show.
  The evidence is `measured.neutral_gate` (the tightest chroma limit reached) and `neutral_share` (the share of
  mid-tones within it). A gate of null means nothing near the camera's balance looked grey (a close-up of one colour,
  or a camera set for very different light), so the camera's balance stands. To override a clip, set `"neutral_rgb"` in its `assumed`
  section: `[1, 1, 1]` keeps the camera's balance; any other value is the colour grey records as.
- A clip shot on a tripod: set `"support": "tripod"` in its `assumed` section. It is then never stabilized, and search
  lists it as steady throughout. The picture alone can't always tell a still camera from a subject that fills the frame.
- People's names and skin levels live in `people.json` in your library. They never go in this repository.

Your library (clips, sidecars, `people.json`) and your renders stay on your machine. Keep them out of this repository.

## Credits

The film look uses LUTs baked with [spektrafilm](https://github.com/andreavolpato/spektrafilm) (film modeling
powered by spektrafilm). The LUTs are CC BY-SA 4.0. See `looks/`.
