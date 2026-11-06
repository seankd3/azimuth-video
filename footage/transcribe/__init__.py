"""What was said, when, and by which voice, in a clip or any recording.

One transcript shape serves both: `words` (text, start, end, confidence, speaker) and `voices` (number, first and last
word, seconds and print), made by hear.hear. A clip's sidecar keeps it as its `transcript` section; a recording keeps
it as NAME.transcript.json with the voices' names and its Markdown, SRT and VTT (formats.py, python -m
footage.transcribe). Who a voice is lives in the Library's people.json (people.py).

hear.py    recognition (Parakeet) and voices (clustered TitaNet prints)
formats.py turns, and the JSON, Markdown, SRT and VTT files
__main__   python -m footage.transcribe
"""
from pathlib import Path

from .hear import audio, hear, identity


def clip(clip: Path, sc: dict) -> dict:
    """A clip's transcript section."""
    return hear(audio(clip))
