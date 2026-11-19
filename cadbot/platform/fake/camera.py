# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Fake camera: plays a video file or images from CADBOT_FAKE_CAMERA, else a test pattern."""

from __future__ import annotations

import os
import time
from pathlib import Path

import cv2
import numpy as np

from cadbot.platform.base import Frame


def test_pattern(width: int = 1280, height: int = 720, t: float = 0.0) -> np.ndarray:
    """Synthetic BGR colour bars with a moving square, so the frame gate sees change."""
    image = np.zeros((height, width, 3), dtype=np.uint8)
    colours = [(255, 255, 255), (0, 255, 255), (255, 255, 0), (0, 255, 0),
               (255, 0, 255), (0, 0, 255), (255, 0, 0)]
    bar = width // len(colours)
    for i, colour in enumerate(colours):
        image[:, i * bar : (i + 1) * bar] = colour
    x = int((t * 100) % (width - 80))
    image[height // 2 - 40 : height // 2 + 40, x : x + 80] = 0
    return image


class FakeCamera:
    def __init__(self, source: str | None = None) -> None:
        self._source = source if source is not None else os.environ.get("CADBOT_FAKE_CAMERA")
        self._images: list[np.ndarray] = []
        self._video: cv2.VideoCapture | None = None
        self._index = 0
        self._opened = False
        self.focus: int | None = None
        self.exposure: int | None = None

    def open(self) -> None:
        if self._source:
            path = Path(self._source)
            if path.is_dir():
                self._images = [img for p in sorted(path.iterdir())
                                if (img := cv2.imread(str(p))) is not None]
            else:
                self._video = cv2.VideoCapture(str(path))
        self._opened = True

    def read(self) -> Frame | None:
        if not self._opened:
            return None
        now = time.time()
        if self._video is not None:
            ok, image = self._video.read()
            if not ok:
                self._video.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, image = self._video.read()
            return Frame(image, now) if ok else None
        if self._images:
            image = self._images[self._index % len(self._images)]
            self._index += 1
            return Frame(image, now)
        self._index += 1
        return Frame(test_pattern(t=self._index / 15), now)

    def set_focus(self, value: int | None) -> None:
        self.focus = value

    def set_exposure(self, value: int | None) -> None:
        self.exposure = value

    def close(self) -> None:
        if self._video is not None:
            self._video.release()
        self._opened = False


def make_camera() -> FakeCamera:
    return FakeCamera()
