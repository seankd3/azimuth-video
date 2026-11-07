# Azimuth Video

Azimuth Video is a local, agent-friendly toolkit for camera footage. It files clips, describes and measures them,
and renders graded edits. Its models run on your own machine; the describer is whichever agent or vision model you name.

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
3. **Describe.** It writes a question for each clip into `LIBRARY/.questions/DAY/FILE/KEY/`: frames sampled across the
   take and `question.json`, with the prompt and the answer's schema. Your describer (an AI agent, or a vision model
   with a small script around it) writes `answer.json` beside them: a summary, tags, shot size, camera movement and
   usable moments. The next run checks each answer, stores it and then removes the question; a bad answer is reported
   and stays. KEY changes when what the question was asked from changes, so a late answer never lands on a new question.
4. **Transcribe.** Parakeet transcribes the speech, and voiceprints of every 1.5 s of it, clustered, tell the voices
   apart. The same transcriber runs on any recording: `python -m footage.transcribe FILE` writes its words, Markdown
   and SRT/VTT subtitles. A clip's sidecar and a recording's `.transcript.json` hold one shape: every word with its
   voice, and every voice with its print. The code is the `footage/transcribe/` package: `hear.py` hears,
   `formats.py` writes the files.
5. **Measure.** It measures exposure, white balance, clipping, sharpness and motion. It also finds faces and measures how they are lit.
6. **Find focus pulls.** It tracks sharpness across the frame on every frame. It records each rack focus, when it starts and when it settles.
7. **Recognize people.** It groups faces into people across the whole library, and knows people's voices once you
   name them in a transcript. You can add names to `people.json`.
8. **Index.** EmbeddingGemma 2 turns every 5 seconds of a clip into two vectors, one for the picture and one for the
   sound, in the same space as text. Search can then rank moments by a phrase ("a forklift backing up"), by a sound
   ("a grinder"), or by how much they look like a moment of another clip. The model runs on your machine, with the
   Hugging Face hub switched off.
9. **Grade and render.** It renders an OpenTimelineIO timeline, or single stills, through one picture graph:
   - each shot gets its own exposure and white-balance correction;
   - the whole edit is printed in one look you choose: a spektrafilm film-stock simulation, how hard it is printed,
     its warmth, halation around what the camera clipped (lamps, speculars, backlit edges; not white shirts or
     walls), and lens vignette;
   - the looks are files in `looks/`: `cinema` (the default house look), `cinema-glow`, `classic`, `cinestill-800t`,
     `kodak-gold-200`, `portra-400`, `fuji-pro-400h` and `fuji-superia-400`, with stronger versions of CineStill and Gold.
     `python -m footage.grade` lists them;
   - `natural` is the true-to-life grade: no film, glow or vignette. Each shot's shade is balanced apart from its
     lit surfaces, so mixed light leaves no tint. A bright room stays bright, and a dark shot is shown as exposed (for its lit part, a doorway at night), darker, with colour fading out of its shadows as it does for the eye at night.
     The highlights are kept under the shoulder (the look's `key`, `dark`, `night`, `headroom`, `shadows` and `tint` settings).

   The master is 10-bit HEVC at the largest 2.39:1 frame the footage supports (5162x2160 for 4K 1.6x anamorphic).
   A timeline can ask for the whole recorded frame, a smaller height and a smaller file instead, for example a
   documentation copy of a long talk: `{"look": "natural", "frame": "full", "height": 1080, "crf": 28}`.

Edits are made in code: an agent writes the timeline, and the toolkit grades and renders it. A timeline can also hold title cards (an OTIO
GeneratorReference of kind `title`) and music, and `python -m footage.music TRACK` finds a track's beats and
loudness so cuts can land on the beat.

## Use

```bash
python -m footage                     # file the inbox, then fill every sidecar section that is missing or out of date
python -m footage.find hands --size close-up   # find shots; each line shows its focus pulls and speech
python -m footage.find --shows "a forklift backing up" --top 10   # moments whose picture matches; --sounds for sound
python -m footage.find --like 2026-10-29/CLIP0001@12   # moments that look like second 12 of that clip
python -m footage.render EDIT.otio [--look cinema,kodak-gold-200]   # render a timeline to "EDIT - LOOK.mp4"
python -m footage.render --stills OUT_DIR [--look ...] CLIP@SECONDS ...   # full-resolution graded stills
python -m footage.frame CLIP 02:05 [--out PATH.jpg]   # one desqueezed, ungraded frame of a clip (card, Ingest or Library), for a transcript's timestamp
python -m footage.assume 2026-10-29 squeeze=1.6   # set what the file doesn't record, for clips or whole days
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

- Python 3.12 with numpy, scipy, colour-science, opentimelineio, opencv-python-headless, onnx-asr, pillow, mediapipe and dlib,
  plus torch and torchvision built for CUDA, transformers and sentence-transformers.
- `onnxruntime-gpu` (Microsoft's aarch64 wheels for CUDA 13) with NVIDIA's `nvidia-curand` wheel beside torch's CUDA
  wheels, so Parakeet, Silero and TitaNet run on the GPU. With the CPU `onnxruntime` they run on the CPU.
- `ffmpeg` and `ffprobe`, plus `ffmpeg-gpu`: an FFmpeg build with NVDEC, zscale and 10/12-bit x265 (for example, a BtbN build).
- LibRaw 0.22 or later (`dcraw_emu`, `raw-identify`, `libraw.so`), for RAW clips, built from source into
  `~/.local/share/footage/vendor/libraw` with `-DLIBRAW_MAX_CR3_RAW_FILE_SIZE` raised: packaged builds refuse a RAW
  clip over 2 GB, about 11 seconds of 8K.
- Models in `~/.local/share/footage/models`: Google's BlazeFace full range and dlib's face recognition, NVIDIA's TitaNet-large
  (exported to ONNX with NeMo, as `titanet-large-nvidia`), Parakeet TDT 0.6B v2, and EmbeddingGemma 2 (`google/embeddinggemma-2`, as `embeddinggemma-2`). Keep the folder read-only (`chmod -R a-w`): a section is identified
  by its models' file names and sizes, so a new model or version goes in under a new name, never over an old file.

## Site settings

Settings for your own footage live outside the repository, in `~/.config/azimuth-video/config.json`
(or the path in `AZIMUTH_VIDEO_CONFIG`). Every key is optional:

```json
{
  "context": "One sentence about what the footage shows, given to the describer.",
  "describer": "agent or model name",
  "timezone": "Area/City",
  "look": "cinema",
  "cameras": [{"model_prefix": "Canon EOS", "squeeze": 1.6, "log": "Canon Log 3", "gamut": "Cinema Gamut"}]
}
```

- Without a timezone, shooting days follow the system's local time.
- `describer` names who answers the description questions. It is part of each description's id, so naming another
  describer redoes every description.
- `look` is the house look: every render and still uses it, so every clip is printed the same way, unless a timeline's
  `metadata["footage"]["look"]` or `--look` names another. Each shot still gets its own white balance and exposure first.
- Without a matching camera rule, a clip's squeeze is unknown. Set it with `python -m footage.assume CLIP squeeze=1.6`.
  Change sidecars through `footage.assume` rather than by hand: it waits for any write in progress, so nothing is lost.
- White balance trusts the camera's own balance and corrects only what the frame's near-grey surfaces show.
  The evidence is `measured.neutral_gate` (the tightest chroma limit reached) and `neutral_share` (the share of
  mid-tones within it). A gate of null means nothing near the camera's balance looked grey (a close-up of one colour,
  or a camera set for very different light), so the camera's balance stands. To override a clip: `python -m footage.assume CLIP neutral_rgb=[1,1,1]`
  keeps the camera's balance; any other value is the colour grey records as, and `null` goes back to the measured one.
- People's names and skin levels live in `people.json` in your library. They never go in this repository. An edit
  there holds at once: search and render look a clip's person up when they read it.
- A voice gets a name when you give it one: `python -m footage.transcribe NAME.transcript.json --names "Ana,Ben"`
  records each named voice's print, with the file and time it came from, under that person in `people.json`. After
  that, a new transcript and every clip at each run give a voice the name of the person it matches, and record that
  print too, so the library learns each voice from more recordings. A wrong name is fixed by renaming that voice in its
  transcript: its print moves to the new name. `python -m footage.find --person Ana` finds clips where Ana is seen or
  heard. The match threshold (`people.VOICE`, 0.72) was tuned on four recordings of six people: one person scored
  0.79 to 0.90 across files, two different people at most 0.63.

Your library (clips, sidecars, `people.json`) and your renders stay on your machine. Keep them out of this repository.
Face and voice prints are biometric data about the people you film: `people.json`, sidecars and `.transcript.json`
files hold them, and none of them may ever be committed or shared.

## Credits

The film look uses LUTs baked with [spektrafilm](https://github.com/andreavolpato/spektrafilm) (film modeling
powered by spektrafilm). The LUTs are CC BY-SA 4.0. See `looks/`.
