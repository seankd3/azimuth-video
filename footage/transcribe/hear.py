"""What was said in a recording, when, and by which voice: Parakeet words and clustered TitaNet voiceprints.

TitaNet-large is NVIDIA's own release, exported to ONNX with NVIDIA NeMo and run by onnxruntime; `features` is NeMo's
mel front end in numpy, with NeMo's own filters, matching it to 3e-5."""
import subprocess
from functools import cache
from pathlib import Path

import numpy as np

from .. import models, probe

VERSION = 4  # bump when transcription, voices, voiceprints or the transcript's shape change
PARAKEET = models.FOLDER / "parakeet-tdt-0.6b-v2"
TITANET = models.FOLDER / "titanet-large-nvidia"
SILERO = models.FOLDER / "silero-vad"  # where speech is; not in identity(): its file has never changed since the first
# transcript, and setup/models.txt pins it by sha256
RATE = 16000
FRAME = 0.08  # Parakeet's time step: 10 ms features, subsampled 8x
WINDOW, HOP = 1.5, 0.75  # a voice is judged on 1.5 s of speech every 0.75 s,
NEAR, FINE, FINE_HOP = 1.5, 0.75, 0.25  # and again on 0.75 s every 0.25 s within 1.5 s of a change of voice
MOST = 8  # the most voices told apart when the count is not given
EVIDENCE = 4  # prints (about 3.75 s of speech) a voice needs to be told apart from the others
ONE_VOICE = 0.7  # voices whose prints are this alike are one person: one presenter's split voices measured 0.88 to
# 0.95 alike, and a second person 0.12 to 0.18


def identity(sc: dict) -> dict:
    return {"transcribe": VERSION, "models": models.identity(PARAKEET, TITANET)}


@cache
def recognizer():
    import onnx_asr
    import onnxruntime as rt
    # Waiting threads sleep instead of spinning: at idle priority a spinning pool waits on its slowest preempted
    # thread, which halved the speed on a busy machine.
    so = rt.SessionOptions()
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    run = models.providers()
    return onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v2", str(PARAKEET), sess_options=so, providers=run).with_vad(
        onnx_asr.load_vad("silero", str(SILERO), providers=run)).with_timestamps()


@cache
def embedder():
    import onnxruntime as rt
    so = rt.SessionOptions()
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    return rt.InferenceSession(str(TITANET / "titanet_large.onnx"), so, providers=models.providers())


@cache
def filters() -> tuple[np.ndarray, np.ndarray]:
    """NeMo's mel filters (80 x 257) and its 400-sample Hann window, centred in the 512-point FFT."""
    window = np.zeros(512, np.float32)
    window[56:456] = np.load(TITANET / "window.npy")
    return np.load(TITANET / "mel_filters.npy"), window


def features(x: np.ndarray) -> tuple[np.ndarray, int]:
    """TitaNet's input for samples at RATE: NeMo's eval-mode log-mel features (pre-emphasis 0.97, 25 ms windows every
    10 ms, 80 mels, each normalized over the frames), padded to a multiple of 16 frames, and how many frames are real."""
    fb, window = filters()
    x = np.concatenate([x[:1], x[1:] - 0.97 * x[:-1]]).astype(np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(np.pad(x, 256), 512)[::160]
    valid = len(x) // 160
    mel = np.log((np.abs(np.fft.rfft(frames * window, axis=1)) ** 2) @ fb.T + 2 ** -24).T[:, :valid]
    mel = (mel - mel.mean(1, keepdims=True)) / (mel.std(1, ddof=1, keepdims=True) + 1e-5)
    return np.pad(mel, ((0, 0), (0, -valid % 16))).astype(np.float32), valid


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
    out = []
    for s, t in spans:
        mel, valid = features(a[int(s * RATE):int(t * RATE)])
        out.append(embedder().run(["embs"], {"audio_signal": mel[None], "length": np.array([valid], np.int64)})[0][0])
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
    """Voices joined, most alike first. Without a count, two voices at least ONE_VOICE alike are one, and then a voice
    with too few prints to judge (EVIDENCE) joins the voice it is most like; with one, the two most alike voices join
    until there are `count`."""
    while True:
        centre = centres(X, labels)
        sizes = {k: labels.count(k) for k in centre}
        alike = lambda pair: float(centre[pair[0]] @ centre[pair[1]])
        if len(sizes) == 1:
            return labels
        if count is None:
            pair = max(((p, q) for p in centre for q in centre if p < q), key=alike)
            small = min(sizes, key=sizes.get)
            if alike(pair) >= ONE_VOICE:
                gone, into = sorted(pair, key=sizes.get)
            elif sizes[small] < EVIDENCE:
                gone, into = max(((small, k) for k in centre if k != small), key=alike)
            else:
                return labels
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


def hear(a: np.ndarray, speakers: int | None = None) -> dict:
    """A transcript: every word (text, start, end, confidence, speaker) and every voice (its number, first and last
    word, seconds of speech and print), voices numbered by first appearance. Every 1.5 s of speech gets a voiceprint,
    the prints are clustered into the voices they show, and each word goes to the voice whose prints overlap it most.
    Where the voice changes, a 1.5 s print straddles both voices, so the words there are judged again on 0.75 s
    prints, each given the nearest voice. Told `speakers`, the voices are split to that many if they show fewer, and
    joined, most alike first, if they show more: a joined voice judges its words as the voices it is made of."""
    lines = [r for r in recognizer().recognize(a, sample_rate=RATE) if r.text.strip()] if a.size >= RATE else []
    every = [w for r in lines for w in words(r)]
    if not every:
        return {"words": [], "voices": []}
    coarse = windows([(round(r.start, 2), round(r.end, 2)) for r in lines], WINDOW, HOP)
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
    centre = centres(X, labels)
    order = list(dict.fromkeys(w["speaker"] for w in every))
    for w in every:  # voices numbered by first appearance, so names can be given in the order people speak
        w["speaker"] = order.index(w["speaker"])
    voices = []
    for i, k in enumerate(order):
        said = [w for w in every if w["speaker"] == i]
        voices.append({"voice": i, "start": said[0]["start"], "end": said[-1]["end"],
                       "seconds": round(sum(w["end"] - w["start"] for w in said), 1),
                       "print": [round(float(x), 4) for x in centre[k]]})
    return {"words": every, "voices": voices}
