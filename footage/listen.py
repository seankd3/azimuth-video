"""What was said in a clip, when, and by which voice: Parakeet transcript and clustered TitaNet voiceprints."""
import subprocess
from functools import cache
from pathlib import Path

import numpy as np

from . import models, probe

VERSION = 2  # bump when transcription, voices or voiceprints change
PARAKEET = models.FOLDER / "parakeet-tdt-0.6b-v2"
TITANET = models.FOLDER / "nemo_en_titanet_small.onnx"
RATE = 16000
FRAME = 0.08  # Parakeet's time step: 10 ms features, subsampled 8x
WINDOW, HOP = 1.5, 0.75  # a voice is judged on 1.5 s of speech every 0.75 s,
NEAR, FINE, FINE_HOP = 1.5, 0.75, 0.25  # and again on 0.75 s every 0.25 s within 1.5 s of a change of voice
MOST = 8  # the most voices told apart when the count is not given
EVIDENCE = 4  # prints (about 3.75 s of speech) a voice needs to be told apart from the others


def identity(sc: dict) -> dict:
    return {"listen": VERSION, "models": models.identity(PARAKEET, TITANET)}


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


def audio(clip: Path) -> np.ndarray:
    """The clip's sound as mono at RATE; nothing for a clip shot without sound."""
    if not any(st["codec_type"] == "audio" for st in probe.ffprobe(clip)["streams"]):
        return np.zeros(0, np.float32)
    # -xerror: a damaged track fails the pass (and is retried) instead of passing for silence.
    raw = subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(clip), "-vn", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


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


def voice(span: dict, by_voice: dict):
    """The voice whose spans overlap the span most; when none overlaps it, the voice with the nearest span. None only
    when there are no voices."""
    overlap = {k: sum(max(0.0, min(span["end"], e) - max(span["start"], s)) for s, e in ts) for k, ts in by_voice.items()}
    if not overlap or max(overlap.values()) > 0:
        return max(overlap, key=overlap.get, default=None)
    mid = (span["start"] + span["end"]) / 2
    return min(by_voice, key=lambda k: min(max(s - mid, mid - e) for s, e in by_voice[k]))


def windows(spans: list, size: float, hop: float) -> list:
    """Stretches `size` seconds long every `hop` seconds across each span; a shorter span gets one, centred on it."""
    out = []
    for s, e in spans:
        if e - s <= size:
            out.append((max(0.0, (s + e - size) / 2), (s + e + size) / 2))
        else:
            steps = int(np.ceil((e - s - size) / hop)) + 1
            out += [(t, t + size) for t in (min(s + i * hop, e - size) for i in range(steps))]
    return out


def prints(a: np.ndarray, spans: list) -> np.ndarray:
    """Each span's voiceprint, as a unit vector."""
    e = embedder()
    out = []
    for s, t in spans:
        stream = e.create_stream()
        stream.accept_waveform(RATE, a[int(s * RATE):int(t * RATE)])
        stream.input_finished()
        out.append(e.compute(stream))
    v = np.array(out, dtype=np.float64)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def centres(X: np.ndarray, labels: list) -> dict:
    """Each voice's print: the unit mean of its prints."""
    out = {k: X[[i for i, x in enumerate(labels) if x == k]].mean(axis=0) for k in set(labels)}
    return {k: v / np.linalg.norm(v) for k, v in out.items()}


def clusters(X: np.ndarray, count: int | None = None) -> list:
    """Which voiceprints are one voice: spectral clustering of each print's nearest neighbours, with the neighbourhood
    and, unless given, the count chosen by the normalized maximum eigengap (NME-SC, Park et al. 2020)."""
    from scipy.cluster.vq import kmeans2
    from scipy.sparse import csr_matrix, diags, identity
    from scipy.sparse.linalg import eigsh
    n = len(X)
    if n < 2:
        return [0] * n
    sim = X @ X.T
    np.fill_diagonal(sim, -np.inf)
    nearest = np.argsort(-sim, axis=1)
    m = min(MOST + 1, n)
    best = None
    for k in sorted({max(1, round(p * n)) for p in np.linspace(0.01, 0.25, 25)} & set(range(1, n))):
        A = csr_matrix((np.ones(n * k), (np.repeat(np.arange(n), k), nearest[:, :k].ravel())), shape=(n, n))
        A = (A + A.T) / 2
        d = np.asarray(A.sum(axis=1)).ravel()
        L = diags(d) - A
        if m < n - 1:  # Lanczos on c - L finds L's smallest eigenvalues; a dense solve is 200x slower at idle priority
            c = 2 * d.max()
            vals, vecs = eigsh(c * identity(n) - L, k=m, which="LA", rng=np.random.default_rng(0))
            vals = c - vals
        else:
            vals, vecs = np.linalg.eigh(L.toarray())
        o = np.argsort(vals)[:m]
        vals, vecs = vals[o], vecs[:, o]
        gaps = np.diff(vals)
        ratio = (k / n) / (gaps.max() / (vals[-1] + 1e-10) + 1e-10)
        if best is None or ratio < best[0]:
            best = (ratio, min(count or int(np.argmax(gaps)) + 1, m), vecs)
    _, voices, vecs = best
    if voices == 1:
        return [0] * n
    return [int(x) for x in kmeans2(vecs[:, :voices], voices, minit="++", rng=np.random.default_rng(0))[1]]


def join(X: np.ndarray, labels: list, count: int | None = None) -> list:
    """Voices joined, most alike first. Without a count, a voice with too few prints to judge (EVIDENCE) joins the
    voice it is most like; with one, the two most alike voices join until there are `count`."""
    while True:
        centre = centres(X, labels)
        sizes = {k: labels.count(k) for k in centre}
        alike = lambda pair: float(centre[pair[0]] @ centre[pair[1]])
        if count is None:
            small = min(sizes, key=sizes.get)
            if sizes[small] >= EVIDENCE or len(sizes) == 1:
                return labels
            gone, into = max(((small, k) for k in centre if k != small), key=alike)
        elif len(sizes) > count:
            gone, into = max(((p, q) for p in centre for q in centre if p < q), key=alike)
        else:
            return labels
        labels = [into if x == gone else x for x in labels]


def spans_of(spans: list, labels: list) -> dict:
    out: dict = {}
    for span, k in zip(spans, labels):
        out.setdefault(k, []).append(span)
    return out


def hear(a: np.ndarray, speakers: int | None = None) -> tuple[list, dict]:
    """What was said and by which voice: each recognized line with its words, and each voice's print. Every 1.5 s of
    speech gets a voiceprint, the prints are clustered into the voices they show, and each word goes to the voice
    whose prints overlap it most. Where the voice changes, a 1.5 s print straddles both voices, so the words there are
    judged again on 0.75 s prints, each given the nearest voice. Told `speakers`, the voices are split to that many
    if they show fewer, and joined, most alike first, if they show more: a joined voice judges its words as the
    voices it is made of. A line goes to the voice its words overlap most."""
    lines = []
    for r in recognizer().recognize(a, sample_rate=RATE):
        text = r.text.strip()
        if text:
            lines.append({"start": round(r.start, 2), "end": round(r.end, 2), "text": text,
                          "confidence": confidence(r.logprobs), "words": words(r)})
    if not lines:
        return lines, {}
    every = [w for line in lines for w in line["words"]]
    coarse = windows([(line["start"], line["end"]) for line in lines], WINDOW, HOP)
    X = prints(a, coarse)
    labels = join(X, clusters(X))
    if speakers and speakers > len(set(labels)):
        labels = clusters(X, speakers)
    centre = centres(X, labels)
    by_voice = spans_of(coarse, labels)
    for w in every:
        w["speaker"] = voice(w, by_voice)
    changes = [(p["end"] + w["start"]) / 2 for p, w in zip(every, every[1:]) if p["speaker"] != w["speaker"]]
    fine = windows([(max(0.0, c - NEAR), min(a.size / RATE, c + NEAR)) for c in changes], FINE, FINE_HOP)
    if fine:
        keys = list(centre)
        nearest = np.argmax(prints(a, fine) @ np.array([centre[k] for k in keys]).T, axis=1)
        by_fine = spans_of(fine, [keys[i] for i in nearest])
        for w in every:  # only words near a change overlap a short print
            if any(min(w["end"], e) > max(w["start"], s) for ts in by_fine.values() for s, e in ts):
                w["speaker"] = voice(w, by_fine)
    if speakers:
        group = dict(zip(labels, join(X, labels, speakers)))
        labels = [group[k] for k in labels]
        for w in every:
            w["speaker"] = group[w["speaker"]]
    by_word = spans_of([(w["start"], w["end"]) for w in every], [w["speaker"] for w in every])
    for line in lines:
        line["speaker"] = voice(line, by_word)
    return lines, {k: v for k, v in centres(X, labels).items() if k in by_word}


def listen(clip: Path, sc: dict) -> dict:
    a = audio(clip)
    if a.size < RATE:
        return {"speech_seconds": 0.0, "segments": [], "speakers": []}
    lines, voices = hear(a)
    segments = [{"start": l["start"], "end": l["end"], "text": l["text"], "confidence": l["confidence"],
                 "speaker": None if l["speaker"] is None else f"s{l['speaker']}"} for l in lines]
    said = [w for l in lines for w in l["words"]]
    speakers = [{"id": f"s{k}", "seconds": round(sum(w["end"] - w["start"] for w in said if w["speaker"] == k), 1),
                 "voiceprint": [round(float(x), 4) for x in v]} for k, v in sorted(voices.items())]
    return {"speech_seconds": round(sum(s["end"] - s["start"] for s in segments), 1),
            "segments": segments, "speakers": speakers}
