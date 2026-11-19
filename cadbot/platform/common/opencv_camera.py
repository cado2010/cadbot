# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""USB (UVC) camera through OpenCV. The backend differs per platform: DirectShow or V4L2."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

import cv2
import numpy as np

from cadbot.platform.base import Frame

log = logging.getLogger(__name__)


def looks_like_night(image: np.ndarray, threshold: float = 3.0) -> bool:
    """IR night mode gives a colourless picture: all three channels nearly equal."""
    small = cv2.resize(image, (64, 36), interpolation=cv2.INTER_AREA).astype(np.int16)
    b, g, r = small[..., 0], small[..., 1], small[..., 2]
    spread = (np.abs(b - g) + np.abs(g - r) + np.abs(b - r)).mean() / 3
    return bool(spread < threshold)


class OpenCVCamera:
    def __init__(self, *, index: int, backend: int, width: int = 1280, height: int = 720,
                 fps: int = 15, detect_night: bool = False,
                 control: Callable[[str, int | None], None] | None = None) -> None:
        self._index = index
        self._backend = backend
        self._size = (width, height)
        self._fps = fps
        self._detect_night = detect_night
        self._control = control
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> None:
        cap = cv2.VideoCapture(self._index, self._backend)
        if not cap.isOpened():
            raise RuntimeError(f"camera {self._index} could not be opened")
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._size[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._size[1])
        cap.set(cv2.CAP_PROP_FPS, self._fps)
        self._cap = cap
        log.info("camera open: %dx%d", cap.get(cv2.CAP_PROP_FRAME_WIDTH),
                 cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    def read(self) -> Frame | None:
        if self._cap is None:
            return None
        ok, image = self._cap.read()
        if not ok or image is None:
            return None
        night = self._detect_night and looks_like_night(image)
        return Frame(image=image, timestamp=time.time(), is_night=night)

    def set_focus(self, value: int | None) -> None:
        self._set("focus", value)

    def set_exposure(self, value: int | None) -> None:
        self._set("exposure", value)

    def _set(self, what: str, value: int | None) -> None:
        if self._control is not None:
            self._control(what, value)
            return
        if self._cap is None:
            return
        auto, prop = {
            "focus": (cv2.CAP_PROP_AUTOFOCUS, cv2.CAP_PROP_FOCUS),
            "exposure": (cv2.CAP_PROP_AUTO_EXPOSURE, cv2.CAP_PROP_EXPOSURE),
        }[what]
        if value is None:
            self._cap.set(auto, 1)
        else:
            self._cap.set(auto, 0)
            self._cap.set(prop, value)

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
