# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Face detection (YuNet) and face embeddings (SFace), both OpenCV ONNX models on the CPU.

A sensor: it reports boxes, angles and embeddings. Matching a face to a name is a
similarity score (see people/matcher.py); Claude decides what to do with it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import cv2
import numpy as np

log = logging.getLogger(__name__)

Angle = Literal["frontal", "left", "right", "profile"]

YUNET = "faces/face_detection_yunet_2023mar.onnx"
SFACE = "faces/face_recognition_sface_2021dec.onnx"


@dataclass(frozen=True)
class DetectedFace:
    box: tuple[int, int, int, int]
    """x, y, w, h in full-frame pixels."""
    score: float
    angle: Angle
    embedding: np.ndarray
    """L2-normalised SFace feature (128 floats)."""

    @property
    def centre(self) -> tuple[float, float]:
        x, y, w, h = self.box
        return x + w / 2, y + h / 2


class FaceAnalyzer(Protocol):
    def analyze(self, image: np.ndarray) -> list[DetectedFace]: ...


def estimate_angle(landmarks: np.ndarray) -> Angle:
    """Head turn from YuNet's landmarks: nose position between the eyes.

    Landmarks: right eye, left eye, nose tip, right mouth corner, left mouth corner.
    "left"/"right" are as seen by the camera.
    """
    (rex, _rey), (lex, _ley), (nx, _ny) = landmarks[0], landmarks[1], landmarks[2]
    eye_dist = abs(lex - rex) or 1.0
    offset = (nx - (rex + lex) / 2) / eye_dist
    if abs(offset) > 0.45:
        return "profile"
    if offset > 0.15:
        return "right"
    if offset < -0.15:
        return "left"
    return "frontal"


def normalise(vector: np.ndarray) -> np.ndarray:
    v = vector.astype(np.float32).reshape(-1)
    return v / (float(np.linalg.norm(v)) or 1.0)


class YuNetSFace:
    def __init__(self, models_dir: Path, *, score_threshold: float = 0.8,
                 min_face_px: int = 40, detect_width: int = 640) -> None:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        self._detector = cv2.FaceDetectorYN.create(str(models_dir / YUNET), "", (320, 320),
                                                   score_threshold, 0.3, 20)
        self._recognizer = cv2.FaceRecognizerSF.create(str(models_dir / SFACE), "")
        self.min_face_px = min_face_px
        self.detect_width = detect_width

    def analyze(self, image: np.ndarray) -> list[DetectedFace]:
        h, w = image.shape[:2]
        scale = self.detect_width / w if w > self.detect_width else 1.0
        small = cv2.resize(image, (round(w * scale), round(h * scale))) if scale != 1.0 \
            else image
        self._detector.setInputSize((small.shape[1], small.shape[0]))
        _, rows = self._detector.detect(small)
        faces: list[DetectedFace] = []
        for row in rows if rows is not None else []:
            full = row.copy()
            full[:14] /= scale  # back to full-frame coordinates
            x, y, fw, fh = (int(v) for v in full[:4])
            if min(fw, fh) < self.min_face_px:
                continue
            aligned = self._recognizer.alignCrop(image, full)
            feature = self._recognizer.feature(aligned)
            faces.append(DetectedFace(
                box=(x, y, fw, fh), score=float(full[14]),
                angle=estimate_angle(full[4:14].reshape(5, 2)), embedding=normalise(feature)))
        return faces
