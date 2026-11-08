"""Faces in a frame: who they are (an identity fingerprint) and how they are lit (lit and shadow cheek, in scene light).

dlib finds the faces with its CNN detector on the GPU (0.03 s a frame), places five points on each (the corners of
both eyes and the base of the nose), and makes the fingerprint with its ResNet on that alignment. Google's BlazeFace
was tried first: it missed most faces a third of the frame tall, and faces in profile.
"""
import threading
from functools import cache

import numpy as np

from . import color, models

VERSION = 4  # bump when detection, recognition or cheek measurement changes
DLIB = models.FOLDER / "dlib-faces"
SMALLEST = 0.08  # faces shorter than this share of the frame are too small to measure or recognize
# Cosine similarity of two fingerprints at which the faces are one person. On 60 tripod clips, 0.94 joined none of 71
# pairs of faces sharing a frame and kept 89% of 122 same-place faces 1 s apart.
SAME = 0.94
# Detector confidence a face needs for a fingerprint. A face in profile scored 0.01 (a clear face 0.5 to 1.1), and its
# fingerprint matched the person beside it at 0.98: such a face is measured for light but identifies nobody.
SURE = 0.3
ONE_AT_A_TIME = threading.Lock()  # the models are shared


def identity() -> dict:
    return {"face": VERSION, "face_models": models.identity(DLIB)}


@cache
def detector():
    import dlib
    return dlib.cnn_face_detection_model_v1(str(DLIB / "mmod_human_face_detector.dat"))


@cache
def recognizer():
    import dlib
    return (dlib.shape_predictor(str(DLIB / "shape_predictor_5_face_landmarks.dat")),
            dlib.face_recognition_model_v1(str(DLIB / "dlib_face_recognition_resnet_model_v1.dat")))


def cheek(lin: np.ndarray, eye, mouth, nose, w: float) -> np.ndarray | None:
    """Median scene-linear colour of a patch on the cheekbone: between eye and mouth corner, out from the nose."""
    cx = (eye[0] + mouth[0]) / 2 + np.sign(eye[0] - nose[0]) * 0.1 * w
    cy = eye[1] * 0.6 + mouth[1] * 0.4
    r = max(round(0.08 * w), 2)
    x0, y0 = round(cx) - r, round(cy) - r
    if x0 < 0 or y0 < 0 or x0 + 2 * r > lin.shape[1] or y0 + 2 * r > lin.shape[0]:
        return None
    return np.median(lin[y0:y0 + 2 * r, x0:x0 + 2 * r].reshape(-1, 3), axis=0)


def find(lin: np.ndarray, detail: np.ndarray) -> list[dict]:
    """Faces in one desqueezed scene-linear frame, largest first. `detail` is the same frame at higher resolution,
    so the fingerprint comes from a face big enough to recognize."""
    import dlib
    h, w = lin.shape[:2]
    small, big = color.display(lin), color.display(detail)
    scale = big.shape[1] / w
    with ONE_AT_A_TIME:
        boxes = [(d.rect, d.confidence) for d in detector()(small, 1) if d.rect.height() / h >= SMALLEST]
        shape, recognize = recognizer()
        found = []
        for b, sure in boxes:
            points = np.array([(p.x, p.y) for p in shape(small, b).parts()], float)
            box = dlib.rectangle(*(round(v * scale) for v in (b.left(), b.top(), b.right(), b.bottom())))
            found.append((b, points, np.array(recognize.compute_face_descriptor(big, shape(big, box))) if sure >= SURE else None))
    out = []
    for b, points, fp in found:
        eyes, nose = (points[0:2].mean(axis=0), points[2:4].mean(axis=0)), points[4]
        between = np.mean(eyes, axis=0)
        mouth = nose + 0.6 * (nose - between)  # the mouth sits about as far below the nose as the nose below the eyes
        sides = [cheek(lin, eye, mouth + 0.6 * (eye - between), nose, b.width()) for eye in eyes]
        if any(s is None for s in sides) or min(color.luminance(s) for s in sides) <= 0:
            continue
        lit, shade = sorted(sides, key=color.luminance, reverse=True)
        out.append({"height": round(float(b.height() / h), 3), "key_stops": round(float(np.log2(color.luminance(lit) / 0.18)), 2),
                    "fill_stops": round(float(np.log2(color.luminance(shade) / 0.18)), 2),
                    "cheek_rgb": [round(float(v), 4) for v in lit], "print": None if fp is None else [round(float(v), 3) for v in fp / np.linalg.norm(fp)]})
    return sorted(out, key=lambda x: -x["height"])
