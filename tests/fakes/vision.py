# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Synthetic faces for tests: no images of real people, just scripted detections."""

from __future__ import annotations

import time

import numpy as np

from cadbot.platform.base import Frame
from cadbot.vision.faces import Angle, DetectedFace, normalise


def identity_vector(seed: int, noise: float = 0.0, noise_seed: int = 0) -> np.ndarray:
    """A stable random 'face embedding' per person; noise makes another view of them."""
    base = np.random.default_rng(seed).normal(size=128)
    if noise:
        base = base + np.random.default_rng(10_000 + noise_seed).normal(size=128) * noise
    return normalise(base)


def face(seed: int, x: int = 500, y: int = 200, size: int = 160, angle: Angle = "frontal",
         noise: float = 0.0, noise_seed: int = 0, score: float = 0.95) -> DetectedFace:
    return DetectedFace((x, y, size, size), score, angle,
                        identity_vector(seed, noise, noise_seed))


def frame(value: int = 60, night: bool = False) -> Frame:
    image = np.full((720, 1280, 3), value, dtype=np.uint8)
    image[300:420, 500:780] = (value + 80) % 256  # some structure for the gate
    return Frame(image, time.time(), night)


class FakeReader:
    """Stands in for FrameReader: tests push frames in."""

    def __init__(self) -> None:
        self.frame: Frame | None = None
        self.started = self.stopped = False

    def push(self, f: Frame) -> None:
        self.frame = f

    def start(self) -> None:
        self.started = True

    def latest(self) -> Frame | None:
        return self.frame

    def stop(self) -> None:
        self.stopped = True


class FakeAnalyzer:
    """Returns whatever faces the test says are in the next frame."""

    def __init__(self) -> None:
        self.faces: list[DetectedFace] = []
        self.calls = 0

    def analyze(self, image: np.ndarray) -> list[DetectedFace]:
        self.calls += 1
        return list(self.faces)
