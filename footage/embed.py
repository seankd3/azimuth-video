"""What each few seconds of a clip look and sound like, as EmbeddingGemma 2 vectors, so footage can be found by words,
by a sound, or by another moment.

A clip is cut into WINDOW-second windows. A window's picture is its frames at one per second, desqueezed as
footage.frame shows them, and its sound is the clip's audio over the same seconds. Each becomes one unit vector in the
model's shared space for text, pictures and sound, so a phrase and a moment can be compared directly: the nearer, the
better the match. The model runs on this machine, loaded from the read-only models folder with the Hugging Face hub
switched off, so nothing it reads leaves it.
"""
import math
import os
from fractions import Fraction
from concurrent.futures import ThreadPoolExecutor
from functools import cache
from io import BytesIO
from pathlib import Path

import numpy as np

from . import models, view
from .frame import jpeg
from .transcribe.hear import RATE, audio

VERSION = 1  # bump when the windows, frame sampling or input format change
MODEL = models.FOLDER / "embeddinggemma-2"
WINDOW = 5  # seconds
WIDTH = 1024  # more than the model's frame budget (140 tokens of 48 px), so frames are only ever shrunk
KINDS = ("picture", "sound")
# Windows the model reads at once. The GPU shares the machine's memory, and the default 32 reached 15 GB on a long clip.
BATCH = 4


def identity(sc: dict) -> dict:
    return {"embed": VERSION, "models": models.identity(MODEL), **view.identity(sc)}


@cache
def model():
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    import torch
    from sentence_transformers import SentenceTransformer
    # Read the weights into memory rather than mapping the file: a mapped tensor took 0.35 s to reach the GPU, so
    # loading took 270 s instead of 4.
    return SentenceTransformer(str(MODEL), local_files_only=True,
                               model_kwargs={"torch_dtype": torch.bfloat16, "disable_mmap": True})


def windows(duration: float) -> list[tuple[float, float]]:
    """WINDOW seconds each, the last running to the end: a short tail joins the window before it, because a window of
    one or two frames scored nearer every phrase than the full windows beside it."""
    n = max(1, round(duration / WINDOW))
    return [(i * WINDOW, duration if i == n - 1 else (i + 1) * WINDOW) for i in range(n)]


def rows(vectors) -> list[list[float]]:
    return [[round(float(x), 4) for x in v] for v in vectors]


def embed(clip: Path, sc: dict) -> dict:
    """The clip's embedding section: one picture vector and one sound vector (None without sound) per window."""
    from PIL import Image
    d = sc["facts"]["duration"]
    spans = windows(d)
    # The middle of each second, but never in the last two frames: a seek there can find no frame to decode.
    last = d - 2 / float(Fraction(sc["facts"]["fps"]))
    seconds = [min((k + min(k + 1, d)) / 2, last) for k in range(math.ceil(d))]
    with ThreadPoolExecutor(8) as pool:
        frames = list(pool.map(lambda t: np.asarray(Image.open(BytesIO(jpeg(clip, sc, t, WIDTH))).convert("RGB")), seconds))
    # The frames are already one a second, so the processor keeps them all.
    picture = model().encode([{"text": "<|video|>", "video": np.stack(frames[int(a):math.ceil(b)])} for a, b in spans],
                             normalize_embeddings=True, processing_kwargs={"video": {"do_sample_frames": False}},
                             batch_size=BATCH)
    sound = audio(clip)
    heard = model().encode([{"text": "<|audio|>", "audio": sound[int(a * RATE):int(b * RATE)]} for a, b in spans],
                           normalize_embeddings=True, batch_size=BATCH) if len(sound) else None
    import torch
    torch.cuda.empty_cache()  # the GPU shares the machine's memory: hand back what this clip used
    return {"window": WINDOW, "picture": rows(picture), "sound": rows(heard) if heard is not None else None}


def phrase(text: str) -> np.ndarray:
    """A search phrase as a vector, to compare with windows of either kind."""
    return model().encode(text, prompt_name="SearchQuery", normalize_embeddings=True)


def scores(sc: dict, kind: str, q: np.ndarray) -> list[tuple[float, float, float]]:
    """Each window of the clip as (start, end, how near it is to q), for the windows' picture or sound."""
    e = sc.get("embedding") or {}
    if not e.get(kind):
        return []
    return [(a, b, float(s)) for (a, b), s in zip(windows(sc["facts"]["duration"]), np.array(e[kind]) @ q)]


def nearest(found: list[tuple[dict, dict]], kind: str, q: np.ndarray, top: int) -> list[dict]:
    """The `top` windows nearest q among the (record, sidecar) pairs found, joined where they touch within a clip,
    nearest first: each is its clip's record with the moment's start, end and nearness."""
    hits = sorted(((s, i, a, b) for i, (_, sc) in enumerate(found) for a, b, s in scores(sc, kind, q)), reverse=True)[:top]
    joined: list[list] = []
    for s, i, a, b in sorted(hits, key=lambda h: (h[1], h[2])):
        if joined and joined[-1][0] == i and joined[-1][2] == a:
            joined[-1][2:] = [b, max(joined[-1][3], s)]
        else:
            joined.append([i, a, b, s])
    return [{**found[i][0], "start": a, "end": b, "near": round(s, 3)} for i, a, b, s in sorted(joined, key=lambda j: -j[3])]
