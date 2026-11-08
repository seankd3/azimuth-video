---
name: transcribe
description: Transcribe an audio or video recording into a speaker-labelled transcript (who said what), fully local, with Markdown, SRT/VTT subtitles and word-timed JSON. Use when asked to transcribe, diarize, make subtitles or captions, or read what was said in a recording, voice memo, meeting, floor talk or video.
---

# transcribe

The transcriber is Azimuth Video's `footage transcribe`, the same code that fills a clip's transcript section. Everything runs on this machine: Parakeet TDT 0.6B v2 (onnx-asr, Silero VAD) for words, and NVIDIA's TitaNet-large voiceprints of every 1.5 s of speech, spectrally clustered, for who spoke when; words near a change of voice are judged again on 0.75 s prints. Both run on the GPU (onnxruntime-gpu). If `footage` is missing, run Azimuth Video's `install.sh`.

```bash
footage transcribe FILE --speakers 2 --names "Ana,Ben" --out DIR
```

- `--speakers N`: the voice count, when known. Without it the count comes from the prints. Told fewer than it hears, it joins the most alike voices.
- `--names`: in the order the voices first speak (Speaker 1 speaks first).
- `--out`: default is beside FILE. Any file ffmpeg reads works. On the GPU, 5 minutes of audio takes about 10 s of recognition.
- It refuses to write over an existing transcript; re-render from its JSON, or delete it to redo.

Writes, for `talk.m4a`, `talk.m4a.transcript.json` (every word: text, start, end, confidence, speaker; the voices' names; turns), and from it `.transcript.md` (a paragraph per turn, mm:ss), `.srt` and `.vtt` (cues of two 42-character lines, at most 6 s, never across voices; `Name:` in SRT, `<v Name>` in VTT).

To see what the video shows at a transcript's timestamp, use `footage frame` (the `azimuth-video` skill).

Voices have names across recordings: a voice that matches a person in the Library's `people.json` comes out with their name, and naming a voice (below) teaches it. Prints are biometric, stay local, never in git. Rename voices after the fact, or fix a word's `speaker` in the JSON by hand, then re-render with no re-run (a renamed voice's print moves to the new name):

```bash
footage transcribe DIR/talk.m4a.transcript.json --names "Ana,Ben,Cy"
```

Limits:
- English only (Parakeet v2).
- Who-said-what: on a 20-minute talk, no count found 3 voices, and the labelled dialogue shows three people taking turns. `--speakers 2` joined the two most alike. Merge or rename voices with `--names` on the JSON (`"Ana,Ana,Ben"` makes two voices one).
- A voice needs about 4 s of speech to stand apart: in a short clip, a second voice that says only a word or two joins the main one.
- Overlapping speech goes to one voice.
- A word lasts from its first frame until the next word starts (at least one 80 ms frame). Check cut points by ear.
- Low `confidence` in the JSON marks words worth checking.

## Where conversations live
Every recorded floor talk, interview or voice memo gets one folder in `~/Documents/Conversations/`, named `YYYY-MM-DD HHMM Topic (people)`, holding `recording.*` (or a link to the video in ~/Videos/Library), `transcript.*` and `notes.md` or `feedback.md`. Add a row to that folder's README index. Then each pain point becomes a floor report under the person who said it. Local only, never git.
