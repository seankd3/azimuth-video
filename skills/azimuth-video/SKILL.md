---
name: azimuth-video
description: Work with camera footage through Azimuth Video - offload a camera card, file clips, find shots by words, look, sound or another shot, see a frame, describe clips, and cut, grade and render an edit in code. Use for any task on B-roll, clips, the video Library, edits, renders, looks or the camera card.
---

# azimuth-video

Azimuth Video is the toolkit for this machine's camera footage. This skill is a link into its repository: `README.md`
there (two folders up from this file, `$(dirname "$(dirname "$(readlink -f ~/.claude/skills/azimuth-video)")")`) is
the manual, with every tool and its flags, the folders, the looks, the models and the settings. Its `AGENTS.md` is how
changes to the toolkit are made. Read both before any footage work. This skill holds only what they can't.

Run any tool as `footage TOOL ARGS` (`python -m footage.TOOL` in the toolkit's environment): `footage` alone files the
inbox and fills every sidecar, `footage find`, `footage render`, `footage frame`, `footage assume`, `footage grade`.
If `footage` is missing, run the repository's `install.sh`.

## House rules

- **Card offload.** Copy each clip from the card into `~/Videos/Ingest`, check the copy byte for byte against the card
  (read back from disk, not the page cache), and run `footage` to file it. Then delete the clip from the card, but
  only once its Library copy matches the card by sha256 and size. Delete nothing else from a card.
- **Edits are code.** You write the timeline (an OpenTimelineIO file, from a script in the edit's folder under
  `~/Videos/Edits/`), and `footage render` grades and renders it. Never install, open or drive a desktop editor, and
  never open a window on the user's desktop. Show results as stills (`footage render --stills`) or finished files.
- **Looks.** The looks are files in the repository's `looks/`; `footage grade` lists them. A shot that reads too bright
  or dark gets `footage assume CLIP exposure=STOPS`, never a new look. A new look is a copied JSON file with new numbers.
- **You are the describer.** `footage` writes description questions under `~/Videos/Library/.questions/`. Answer each
  as its `question.json` asks, from its frames, then run `footage` again to store the answers.
- **Heavy jobs** (the library run, renders, describing many clips) go through `heavy NAME COMMAND`: a systemd unit that
  survives the session, runs one heavy job at a time and can't use the memory the desktop needs. Have COMMAND write a
  log and a status file with its exit code, and check them instead of waiting in the foreground.
- **Models.** Footage, its frames and its sound leave the machine only to Claude. No Chinese model and no runtime from a
  Chinese maker (Qwen, Kimi, YuNet, SFace, sherpa-onnx, ACE-Step) runs here, even locally. Before adding a model,
  check who made it and who exported its file. A local model runs with the network off.
- **Public repository.** Code, commits and issues never name a company, its people, clips or places. Site specifics
  stay in `~/.config/azimuth-video/config.json` and in edit scripts outside the repository.
- **People.** Names and skin levels in the Library's `people.json` are the user's decisions; never guess them. Face and
  voice prints are biometric and never go in git.
