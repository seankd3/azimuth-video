# Azimuth Video

Azimuth Video is a local, agent-friendly toolkit for camera footage. It files clips, describes and measures them,
and renders graded edits. All the models run on your own machine.

Each clip gets one JSON sidecar next to it. The sidecar holds everything the toolkit knows about the clip. Search,
selects and timelines read these sidecars, so an AI agent can find shots and build edits from them.

Each section of a sidecar records an `id`: the code versions, picture geometry, colour decoding, models and settings
it was made from. When one of those changes, the section is out of date: the next run redoes it, a render that needs
it stops, and search leaves it out and says how many clips it skipped sections of.

## What it does

1. **File.** It moves finished clips from an inbox into one folder per shooting day. It never overwrites a file,
   and it leaves duplicates in the inbox. Canon Cinema RAW Light (`.CRM`) files are clips too.
2. **Develop RAW.** LibRaw develops every frame of a RAW clip into the code values the camera records (its log curve
   and gamut), stored as all-intra 12-bit 4:4:4 HEVC in the day's `.developed/` folder. Every step below reads a RAW
   clip's pictures from there, and its sidecar ids record the development, so a new development redoes them.
3. **Describe.** A local vision model writes a summary, tags, shot size, camera movement and usable moments for each clip.
4. **Transcribe.** Parakeet transcribes the speech, and voiceprints of every 1.5 s of it, clustered, tell the voices
   apart. The same transcriber runs on any recording: `python -m footage.transcribe FILE` writes its words, Markdown
   and SRT/VTT subtitles.
5. **Measure.** It measures exposure, white balance, clipping, sharpness and motion. It also finds faces and measures how they are lit.
6. **Find focus pulls.** It tracks sharpness across the frame on every frame. It records each rack focus, when it starts and when it settles.
7. **Recognize people.** It groups faces into people across the whole library. You can add names to `people.json`.
8. **Measure shake.** It follows the camera's motion on every frame and records, second by second, how much the
   camera shakes beyond its smoothed path. Moving hands and people in front of a locked-off camera don't count.
9. **Grade and render.** It renders an OpenTimelineIO timeline, or single stills, through one picture graph:
   - each shot gets its own exposure and white-balance correction;
   - the whole edit is printed in one look you choose: a spektrafilm film-stock simulation, how hard it is printed,
     its warmth, halation around what the camera clipped (lamps, speculars, backlit edges; not white shirts or
     walls), and lens vignette;
   - the looks are files in `looks/`: `cinema` (the default house look), `cinema-glow`, `classic`, `cinestill-800t`,
     `kodak-gold-200`, `portra-400`, `fuji-pro-400h` and `fuji-superia-400`, with stronger versions of CineStill and Gold.
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
python -m footage.frame CLIP 02:05 [--out PATH.jpg]   # one desqueezed, ungraded frame of a clip (card, Ingest or Library), for a transcript's timestamp
python -m footage.assume 2026-10-29 support=tripod   # set what the file doesn't record, for clips or whole days
python -m footage.graded              # every clip graded on its own, in the house look; skips masters still current
bash acceptance.sh                    # filing safety checks on a sandbox of hard links
```

The defaults are `~/Videos/Ingest` for the inbox and `~/Videos/Library` for the library. A layout that stays tidy:

- `~/Videos/Ingest/`: the inbox. Copy from the card here.
- `~/Videos/Library/`: raw footage, one folder per shooting day. Timelines point into it, so keep its name.
- `~/Videos/Edits/<date> <name>/`: finished edits. The timeline, its renders ("EDIT - LOOK.mp4"), and its stills.
- `~/Videos/Graded/<day>/`: every clip graded on its own: "CLIP.MP4.otio" and "CLIP.MP4 - LOOK.mp4", the whole take with its sound.
- `~/Videos/Toolkit tests/<topic>/`: experiments, comparisons and before/after tests. A timeline picks its look
with `metadata["footage"]["look"]`; `--look` overrides it. Runs and renders use idle CPU and disk priority, so they
take only what the desktop leaves.

## Requirements

This toolkit was built and tested on an ARM64 Linux laptop with an NVIDIA RTX Spark GPU.

- Python 3.12 with numpy, scipy, colour-science, opentimelineio, opencv-python-headless, onnx-asr and sherpa-onnx.
- `ffmpeg` and `ffprobe`, plus `ffmpeg-gpu`: an FFmpeg build with NVDEC, zscale and 10/12-bit x265 (for example, a BtbN build).
- LibRaw 0.22 or later (`dcraw_emu`, `raw-identify`), for RAW clips.
- LM Studio, serving `qwen/qwen3.5-35b-a3b`, for the descriptions.
- Models in `~/.local/share/footage/models`: YuNet and SFace (OpenCV Zoo), NeMo TitaNet
  (sherpa-onnx), and Parakeet TDT 0.6B v2. Keep the folder read-only (`chmod -R a-w`): a section is identified
  by its models' file names and sizes, so a new model or version goes in under a new name, never over an old file.
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
  "look": "cinema",
  "cameras": [{"model_prefix": "Canon EOS", "squeeze": 1.6, "log": "Canon Log 3", "gamut": "Cinema Gamut"}]
}
```

- Without a timezone, shooting days follow the system's local time.
- `look` is the house look: every render and still uses it, so every clip is printed the same way, unless a timeline's
  `metadata["footage"]["look"]` or `--look` names another. Each shot still gets its own white balance and exposure first.
- Without a matching camera rule, a clip's squeeze is unknown. Set it with `python -m footage.assume CLIP squeeze=1.6`.
  Change sidecars through `footage.assume` rather than by hand: it waits for any write in progress, so nothing is lost.
- White balance trusts the camera's own balance and corrects only what the frame's near-grey surfaces show.
  The evidence is `measured.neutral_gate` (the tightest chroma limit reached) and `neutral_share` (the share of
  mid-tones within it). A gate of null means nothing near the camera's balance looked grey (a close-up of one colour,
  or a camera set for very different light), so the camera's balance stands. To override a clip: `python -m footage.assume CLIP neutral_rgb=[1,1,1]`
  keeps the camera's balance; any other value is the colour grey records as, and `null` goes back to the measured one.
- A clip shot on a tripod: `python -m footage.assume CLIP support=tripod`. It is then never stabilized, and search
  lists it as steady throughout. The picture alone can't always tell a still camera from a subject that fills the frame.
- People's names and skin levels live in `people.json` in your library. They never go in this repository. An edit
  there holds at once: search and render look a clip's person up when they read it.

Your library (clips, sidecars, `people.json`) and your renders stay on your machine. Keep them out of this repository.

## Credits

The film look uses LUTs baked with [spektrafilm](https://github.com/andreavolpato/spektrafilm) (film modeling
powered by spektrafilm). The LUTs are CC BY-SA 4.0. See `looks/`.
