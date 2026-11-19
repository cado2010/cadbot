# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""cadbot.platform: the only place that knows which hardware cadbot runs on.

`get_platform()` picks `windows`, `pi` or `fake` from CADBOT_PLATFORM (or
CADBOT_FAKE_HARDWARE=1), and auto-detects when neither is set.
"""

from __future__ import annotations

import logging
import os
import sys
from functools import cache
from pathlib import Path

from cadbot.platform.base import (
    AUDIO_SAMPLE_RATE,
    LOGICAL_SCREEN,
    AudioChunk,
    Capabilities,
    Frame,
    InputEvent,
    Platform,
    PlatformName,
    WifiAP,
)

__all__ = [
    "AUDIO_SAMPLE_RATE",
    "LOGICAL_SCREEN",
    "AudioChunk",
    "Capabilities",
    "Frame",
    "InputEvent",
    "Platform",
    "PlatformName",
    "WifiAP",
    "detect_platform_name",
    "get_platform",
]

log = logging.getLogger(__name__)

_VALID: tuple[PlatformName, ...] = ("windows", "pi", "fake")
_PI_MODEL_FILE = Path("/proc/device-tree/model")


def detect_platform_name(
    env: dict[str, str] | None = None,
    sys_platform: str | None = None,
    model_file: Path = _PI_MODEL_FILE,
) -> PlatformName:
    """Resolve the platform name from the environment, then from the machine."""
    env = dict(os.environ) if env is None else env
    explicit = env.get("CADBOT_PLATFORM", "").strip().lower()
    if explicit:
        if explicit not in _VALID:
            raise ValueError(f"CADBOT_PLATFORM={explicit!r}; expected one of {_VALID}")
        return explicit  # type: ignore[return-value]
    if env.get("CADBOT_FAKE_HARDWARE", "").strip() in {"1", "true", "yes"}:
        return "fake"
    plat = sys.platform if sys_platform is None else sys_platform
    if plat == "win32":
        return "windows"
    if plat.startswith("linux") and _is_raspberry_pi(model_file):
        return "pi"
    return "fake"


def _is_raspberry_pi(model_file: Path) -> bool:
    try:
        return "raspberry pi" in model_file.read_text(errors="ignore").lower()
    except OSError:
        return False


@cache
def get_platform() -> Platform:
    """Build the platform once per process."""
    name = detect_platform_name()
    log.info("platform: %s", name)
    if name == "windows":
        from cadbot.platform.windows import build
    elif name == "pi":
        from cadbot.platform.pi import build
    else:
        from cadbot.platform.fake import build
    return build()
