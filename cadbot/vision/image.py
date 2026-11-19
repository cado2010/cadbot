# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Image helpers (no camera access): resizing, JPEG encoding, face crops."""

from __future__ import annotations

import cv2
import numpy as np

SEND_SIZE = (640, 360)  # what Claude sees: about 300 image tokens


def to_jpeg(image: np.ndarray, size: tuple[int, int] = SEND_SIZE, quality: int = 80) -> bytes:
    """Downscale (keeping the whole frame) and JPEG-encode a BGR image."""
    small = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
    ok, data = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("JPEG encoding failed")
    return data.tobytes()


def grey_small(image: np.ndarray, size: tuple[int, int] = (160, 90)) -> np.ndarray:
    """The frame gate's view: tiny, grey, slightly blurred so sensor noise doesn't count."""
    grey = cv2.cvtColor(cv2.resize(image, size, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(grey, (3, 3), 0)


def face_crop(image: np.ndarray, box: tuple[int, int, int, int], size: int = 160,
              margin: float = 0.35) -> np.ndarray:
    """A square crop around a face box (x, y, w, h), for the web UI thumbnail."""
    x, y, w, h = box
    side = int(max(w, h) * (1 + 2 * margin))
    cx, cy = x + w // 2, y + h // 2
    x0, y0 = max(0, cx - side // 2), max(0, cy - side // 2)
    crop = image[y0 : y0 + side, x0 : x0 + side]
    if crop.size == 0:
        crop = image
    return cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)


def encode_jpeg(image: np.ndarray, quality: int = 85) -> bytes:
    ok, data = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("JPEG encoding failed")
    return data.tobytes()
