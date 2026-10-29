"""Faces in a frame: who they are (an identity fingerprint) and how they are lit (lit and shadow cheek, in scene light)."""
import threading
from functools import cache

import numpy as np

from . import color, models

VERSION = 1  # bump when detection, recognition or cheek measurement changes
YUNET = models.FOLDER / "face_detection_yunet_2023mar.onnx"
SFACE = models.FOLDER / "face_recognition_sface_2021dec.onnx"
SMALLEST = 0.08  # faces shorter than this share of the frame are too small to measure or recognize
ONE_AT_A_TIME = threading.Lock()  # one detector and recognizer are shared, and the input size changes per call


def identity() -> dict:
    return {"face": VERSION, "face_models": models.identity(YUNET, SFACE)}


@cache
def detector():
    import cv2
    models.loading(YUNET, SFACE)
    return cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), score_threshold=0.8)


@cache
def recognizer():
    import cv2
    models.loading(YUNET, SFACE)
    return cv2.FaceRecognizerSF.create(str(SFACE), "")


def cheek(lin: np.ndarray, eye, mouth, nose, w: float) -> np.ndarray | None:
    """Median scene-linear colour of a patch on the cheekbone: between eye and mouth corner, out from the nose."""
    cx = (eye[0] + mouth[0]) / 2 + np.sign(eye[0] - nose[0]) * 0.1 * w
    cy = eye[1] * 0.6 + mouth[1] * 0.4
    r = max(round(0.08 * w), 2)
    x0, y0 = round(cx) - r, round(cy) - r
    if x0 < 0 or y0 < 0 or x0 + 2 * r > lin.shape[1] or y0 + 2 * r > lin.shape[0]:
        return None
    return np.median(lin[y0:y0 + 2 * r, x0:x0 + 2 * r].reshape(-1, 3), axis=0)


def bgr(lin: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(color.display(lin)[..., ::-1])  # OpenCV's models take BGR


def find(lin: np.ndarray, detail: np.ndarray) -> list[dict]:
    """Faces in one desqueezed scene-linear frame, largest first. `detail` is the same frame at higher resolution,
    so the fingerprint comes from a face big enough to recognize."""
    h, w = lin.shape[:2]
    small, big = bgr(lin), bgr(detail)
    scale = big.shape[1] / w
    with ONE_AT_A_TIME:
        d = detector()
        d.setInputSize((w, h))
        _, found = d.detect(small)
        found = [f for f in ([] if found is None else found) if f[3] / h >= SMALLEST]
        prints = []
        for f in found:
            g = f.copy()
            g[:14] *= scale
            prints.append(recognizer().feature(recognizer().alignCrop(big, g)).ravel())
    out = []
    for f, fp in zip(found, prints):
        a = cheek(lin, f[4:6], f[10:12], f[8:10], f[2])
        b = cheek(lin, f[6:8], f[12:14], f[8:10], f[2])
        if a is None or b is None or min(color.luminance(a), color.luminance(b)) <= 0:
            continue
        lit, shade = sorted((a, b), key=color.luminance, reverse=True)
        fp = fp / np.linalg.norm(fp)
        out.append({"height": round(float(f[3] / h), 3), "key_stops": round(float(np.log2(color.luminance(lit) / 0.18)), 2),
                    "fill_stops": round(float(np.log2(color.luminance(shade) / 0.18)), 2),
                    "cheek_rgb": [round(float(v), 4) for v in lit], "print": [round(float(v), 3) for v in fp]})
    return sorted(out, key=lambda x: -x["height"])
