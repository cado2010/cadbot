# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Pi camera: Arducam B0506 (UVC) through OpenCV V4L2, focus/exposure with v4l2-ctl.

UNTESTED: written before the Raspberry Pi hardware arrived. Verify with `pytest -m hardware`.
"""

from __future__ import annotations

import logging
import subprocess

import cv2

from cadbot.platform.common.opencv_camera import OpenCVCamera

log = logging.getLogger(__name__)

_CONTROLS = {
    "focus": ("focus_automatic_continuous", "focus_absolute"),
    "exposure": ("auto_exposure", "exposure_time_absolute"),
}


def v4l2_controls(device: str, what: str, value: int | None) -> list[list[str]]:
    """The v4l2-ctl commands that set focus or exposure (None = automatic)."""
    auto, absolute = _CONTROLS[what]
    if what == "exposure":  # V4L2 auto_exposure: 3 = aperture priority (auto), 1 = manual
        auto_value = "3" if value is None else "1"
    else:
        auto_value = "1" if value is None else "0"
    cmds = [["v4l2-ctl", "-d", device, "-c", f"{auto}={auto_value}"]]
    if value is not None:
        cmds.append(["v4l2-ctl", "-d", device, "-c", f"{absolute}={value}"])
    return cmds


def make_camera(index: int = 0) -> OpenCVCamera:
    device = f"/dev/video{index}"

    def control(what: str, value: int | None) -> None:
        for cmd in v4l2_controls(device, what, value):
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                log.warning("v4l2-ctl failed: %s", result.stderr.strip())

    return OpenCVCamera(index=index, backend=cv2.CAP_V4L2, detect_night=True, control=control)
