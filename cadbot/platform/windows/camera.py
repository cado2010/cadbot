# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Windows camera: OpenCV with DirectShow (MJPG). No night vision on a normal webcam."""

from __future__ import annotations

import cv2

from cadbot.platform.common.opencv_camera import OpenCVCamera


def make_camera(index: int = 0) -> OpenCVCamera:
    return OpenCVCamera(index=index, backend=cv2.CAP_DSHOW, detect_night=False)
