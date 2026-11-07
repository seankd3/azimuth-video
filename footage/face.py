"""Faces in a frame: who they are (an identity fingerprint) and how they are lit (lit and shadow cheek, in scene light).

Google's BlazeFace (full range) finds faces and their eyes, nose and mouth; dlib's ResNet, on its own 5-point
alignment, makes the fingerprint. The detector sees a 192-pixel square, so a wide frame is searched in square tiles
half its height, or a face a tenth of the frame tall would be a few pixels.
"""
import threading
from functools import cache

import numpy as np

from . import color, models

VERSION = 2  # bump when detection, recognition or cheek measurement changes
BLAZEFACE = models.FOLDER / "blazeface-full-range-google"
DLIB = models.FOLDER / "dlib-face-recognition"
SMALLEST = 0.08  # faces shorter than this share of the frame are too small to measure or recognize
# Cosine similarity of two fingerprints at which the faces are one person. On 60 tripod clips, 0.94 joined none of 71
# pairs of faces sharing a frame and kept 89% of 122 same-place faces 1 s apart.
SAME = 0.94
ONE_AT_A_TIME = threading.Lock()  # the detector and recognizer are shared


def identity() -> dict:
    return {"face": VERSION, "face_models": models.identity(BLAZEFACE, DLIB)}


@cache
def detector():
    from mediapipe.tasks.python import BaseOptions, vision
    return vision.FaceDetector.create_from_options(vision.FaceDetectorOptions(
        base_options=BaseOptions(model_asset_path=str(BLAZEFACE / "face_detector_full_range.tflite")),
        min_detection_confidence=0.6))


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


def detect(rgb: np.ndarray) -> list[tuple]:
    """Each face in a display frame as (x, y, w, h, score, keypoints in pixels: right eye, left eye, nose, mouth),
    from square tiles half the frame's height that overlap by half, one detection kept where tiles found the same face."""
    import mediapipe as mp
    h, w = rgb.shape[:2]
    side = max(h // 2, 1)
    starts = lambda n: sorted({min(i * side // 2, max(n - side, 0)) for i in range(max(1, -(-2 * n // side)))})
    found = []
    for y0 in starts(h):
        for x0 in starts(w):
            tile = np.ascontiguousarray(rgb[y0:y0 + side, x0:x0 + side])
            for d in detector().detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=tile)).detections:
                b, th, tw = d.bounding_box, *tile.shape[:2]
                kp = [(x0 + k.x * tw, y0 + k.y * th) for k in d.keypoints[:4]]
                found.append((x0 + b.origin_x, y0 + b.origin_y, b.width, b.height, d.categories[0].score, kp))
    kept = []
    for f in sorted(found, key=lambda f: -f[4]):
        if all(overlap(f, k) < 0.3 for k in kept):
            kept.append(f)
    return kept


def overlap(a, b) -> float:
    """Intersection over union of two boxes."""
    ix = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return ix * iy / (a[2] * a[3] + b[2] * b[3] - ix * iy)


def find(lin: np.ndarray, detail: np.ndarray) -> list[dict]:
    """Faces in one desqueezed scene-linear frame, largest first. `detail` is the same frame at higher resolution,
    so the fingerprint comes from a face big enough to recognize."""
    import dlib
    h, w = lin.shape[:2]
    big = color.display(detail)
    scale = big.shape[1] / w
    with ONE_AT_A_TIME:
        found = [f for f in detect(color.display(lin)) if f[3] / h >= SMALLEST]
        shape, recognize = recognizer()
        prints = []
        for x, y, fw, fh, *_ in found:
            box = dlib.rectangle(*(round(v * scale) for v in (x, y, x + fw, y + fh)))
            prints.append(np.array(recognize.compute_face_descriptor(big, shape(big, box))))
    out = []
    for (x, y, fw, fh, _, (right_eye, left_eye, nose, mouth)), fp in zip(found, prints):
        between = np.mean([right_eye, left_eye], axis=0)
        corner = lambda eye: np.asarray(mouth) + 0.6 * (np.asarray(eye) - between)  # each mouth corner, below its eye
        a = cheek(lin, right_eye, corner(right_eye), nose, fw)
        b = cheek(lin, left_eye, corner(left_eye), nose, fw)
        if a is None or b is None or min(color.luminance(a), color.luminance(b)) <= 0:
            continue
        lit, shade = sorted((a, b), key=color.luminance, reverse=True)
        fp = fp / np.linalg.norm(fp)
        out.append({"height": round(float(fh / h), 3), "key_stops": round(float(np.log2(color.luminance(lit) / 0.18)), 2),
                    "fill_stops": round(float(np.log2(color.luminance(shade) / 0.18)), 2),
                    "cheek_rgb": [round(float(v), 4) for v in lit], "print": [round(float(v), 3) for v in fp]})
    return sorted(out, key=lambda x: -x["height"])
