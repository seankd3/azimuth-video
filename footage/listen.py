"""What was said in a clip, when, and by which voice: Parakeet transcript (voxtype's model) and diarized voiceprints."""
import subprocess
from functools import cache
from pathlib import Path

import numpy as np

PARAKEET = Path.home() / ".local/share/voxtype/models/parakeet-tdt-0.6b-v2"
MODELS = Path.home() / ".local/share/footage/models"
RATE = 16000


@cache
def recognizer():
    import onnx_asr
    return onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v2", str(PARAKEET)).with_vad(onnx_asr.load_vad("silero")).with_timestamps()


@cache
def embedder():
    import sherpa_onnx
    return sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(MODELS / "nemo_en_titanet_small.onnx"), num_threads=8))


@cache
def diarizer():
    import sherpa_onnx
    return sherpa_onnx.OfflineSpeakerDiarization(sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(MODELS / "sherpa-onnx-pyannote-segmentation-3-0/model.onnx")), num_threads=8),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(MODELS / "nemo_en_titanet_small.onnx"), num_threads=8),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=0.95),
        min_duration_on=0.3, min_duration_off=0.5))


def audio(clip: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(clip), "-vn", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"],
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


def listen(clip: Path, sc: dict) -> dict:
    a = audio(clip)
    if a.size < RATE:
        return {"model": "parakeet-tdt-0.6b-v2", "speech_seconds": 0.0, "segments": [], "speakers": []}
    segments = []
    for r in recognizer().recognize(a, sample_rate=RATE):
        text = r.text.strip()
        if not text:
            continue
        conf = float(np.exp(np.mean(r.logprobs))) if r.logprobs is not None and len(r.logprobs) else None
        segments.append({"start": round(r.start, 2), "end": round(r.end, 2), "text": text,
                         "confidence": round(conf, 3) if conf is not None else None, "speaker": None})
    speakers = []
    if segments:
        turns = diarizer().process(a).sort_by_start_time()
        by_speaker: dict = {}
        for t in turns:
            by_speaker.setdefault(t.speaker, []).append((t.start, t.end))
        for k, ts in sorted(by_speaker.items()):
            speakers.append({"id": f"s{k}", "seconds": round(sum(e - s for s, e in ts), 1), "voiceprint": voiceprint(a, ts)})
        for seg in segments:  # each line goes to the voice that overlaps it most
            overlap = {k: sum(max(0.0, min(seg["end"], e) - max(seg["start"], s)) for s, e in ts) for k, ts in by_speaker.items()}
            best = max(overlap, key=overlap.get, default=None)
            seg["speaker"] = f"s{best}" if best is not None and overlap[best] > 0 else None
    return {"model": "parakeet-tdt-0.6b-v2", "speech_seconds": round(sum(s["end"] - s["start"] for s in segments), 1),
            "segments": segments, "speakers": speakers}
