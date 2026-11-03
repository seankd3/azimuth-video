"""What was said in a clip, when, and by which voice: Parakeet transcript and diarized voiceprints."""
import subprocess
from functools import cache
from pathlib import Path

import numpy as np

from . import models, probe

VERSION = 1  # bump when transcription, diarization or voiceprints change
PARAKEET = models.FOLDER / "parakeet-tdt-0.6b-v2"
TITANET = models.FOLDER / "nemo_en_titanet_small.onnx"
PYANNOTE = models.FOLDER / "sherpa-onnx-pyannote-segmentation-3-0/model.onnx"
RATE = 16000
FRAME = 0.08  # Parakeet's time step: 10 ms features, subsampled 8x


def identity(sc: dict) -> dict:
    return {"listen": VERSION, "models": models.identity(PARAKEET, TITANET, PYANNOTE)}


@cache
def recognizer():
    import onnx_asr
    import onnxruntime as rt
    # Waiting threads sleep instead of spinning: at idle priority a spinning pool waits on its slowest preempted
    # thread, which halved the speed on a busy machine.
    so = rt.SessionOptions()
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    return onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v2", str(PARAKEET), sess_options=so).with_vad(
        onnx_asr.load_vad("silero")).with_timestamps()


@cache
def embedder():
    import sherpa_onnx
    return sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(TITANET), num_threads=8))


@cache
def diarizer(speakers: int = -1):
    """Who spoke when. Without a known count, voices closer than the threshold are one voice (0.6 split a clip into 23)."""
    import sherpa_onnx
    return sherpa_onnx.OfflineSpeakerDiarization(sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(PYANNOTE)), num_threads=8),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(TITANET), num_threads=8),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=speakers, threshold=0.95),
        min_duration_on=0.3, min_duration_off=0.5))


def audio(clip: Path) -> np.ndarray:
    """The clip's sound as mono at RATE; nothing for a clip shot without sound."""
    if not any(st["codec_type"] == "audio" for st in probe.ffprobe(clip)["streams"]):
        return np.zeros(0, np.float32)
    # -xerror: a damaged track fails the pass (and is retried) instead of passing for silence.
    raw = subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(clip), "-vn", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def voiceprint(a: np.ndarray, turns: list) -> list | None:
    e = embedder()
    vecs = []
    for start, end in turns:
        piece = a[int(start * RATE):int(end * RATE)]
        if len(piece) < RATE:  # under a second says too little about a voice
            continue
        s = e.create_stream()
        s.accept_waveform(RATE, piece)
        s.input_finished()
        vecs.append(np.array(e.compute(s)))
    if not vecs:
        return None
    v = np.mean(vecs, axis=0)
    return [round(float(x), 4) for x in v / np.linalg.norm(v)]


def confidence(logprobs) -> float | None:
    return round(float(np.exp(np.mean(logprobs))), 3) if logprobs is not None and len(logprobs) else None


def words(r) -> list:
    """One recognized line's tokens as words. A token that starts with a space starts a word. A token stamped at a frame
    sounds for at least that frame, and a word lasts until the next word starts or the line ends (inside one stretch
    of speech the gaps are short), so two words stamped at the same frame each last one frame."""
    starts = [i for i, t in enumerate(r.tokens) if i == 0 or t.startswith(" ")]
    out = []
    for i, k in zip(starts, starts[1:] + [len(r.tokens)]):
        until = r.timestamps[k] if k < len(r.tokens) else r.end - r.start
        out.append({"start": round(r.start + r.timestamps[i], 2),
                    "end": round(r.start + max(until, r.timestamps[k - 1] + FRAME), 2),
                    "text": "".join(r.tokens[i:k]).strip(), "confidence": confidence(r.logprobs[i:k])})
    return out


def voice(span: dict, by_speaker: dict):
    """The voice whose turns overlap the span most, or None when none does."""
    overlap = {k: sum(max(0.0, min(span["end"], e) - max(span["start"], s)) for s, e in ts) for k, ts in by_speaker.items()}
    best = max(overlap, key=overlap.get, default=None)
    return best if best is not None and overlap[best] > 0 else None


def hear(a: np.ndarray, speakers: int = -1) -> tuple[list, dict]:
    """What was said and by which voice: each recognized line with its words, every line and word given the voice that
    overlaps it most (a word no turn covers keeps its line's voice); and each voice's turns."""
    lines = []
    for r in recognizer().recognize(a, sample_rate=RATE):
        text = r.text.strip()
        if text:
            lines.append({"start": round(r.start, 2), "end": round(r.end, 2), "text": text,
                          "confidence": confidence(r.logprobs), "words": words(r)})
    by_speaker: dict = {}
    if lines:
        for t in diarizer(speakers).process(a).sort_by_start_time():
            by_speaker.setdefault(t.speaker, []).append((t.start, t.end))
    for line in lines:
        line["speaker"] = voice(line, by_speaker)
        for w in line["words"]:
            w["speaker"] = voice(w, by_speaker)
            if w["speaker"] is None:
                w["speaker"] = line["speaker"]
    return lines, by_speaker


def listen(clip: Path, sc: dict) -> dict:
    a = audio(clip)
    if a.size < RATE:
        return {"speech_seconds": 0.0, "segments": [], "speakers": []}
    lines, by_speaker = hear(a)
    segments = [{"start": l["start"], "end": l["end"], "text": l["text"], "confidence": l["confidence"],
                 "speaker": None if l["speaker"] is None else f"s{l['speaker']}"} for l in lines]
    speakers = [{"id": f"s{k}", "seconds": round(sum(e - s for s, e in ts), 1), "voiceprint": voiceprint(a, ts)}
                for k, ts in sorted(by_speaker.items())]
    return {"speech_seconds": round(sum(s["end"] - s["start"] for s in segments), 1),
            "segments": segments, "speakers": speakers}
