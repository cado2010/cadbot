# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Choosing the platform: CADBOT_PLATFORM, CADBOT_FAKE_HARDWARE, then auto-detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from cadbot.platform import detect_platform_name


def test_explicit_choice_wins(tmp_path: Path) -> None:
    assert detect_platform_name({"CADBOT_PLATFORM": "pi"}, "win32") == "pi"
    assert detect_platform_name({"CADBOT_PLATFORM": " Windows "}, "linux") == "windows"


def test_invalid_choice_is_rejected() -> None:
    with pytest.raises(ValueError, match="CADBOT_PLATFORM"):
        detect_platform_name({"CADBOT_PLATFORM": "mac"}, "darwin")


def test_fake_hardware_flag() -> None:
    assert detect_platform_name({"CADBOT_FAKE_HARDWARE": "1"}, "win32") == "fake"


def test_auto_detection(tmp_path: Path) -> None:
    model = tmp_path / "model"
    model.write_text("Raspberry Pi 5 Model B Rev 1.0\x00")
    assert detect_platform_name({}, "win32") == "windows"
    assert detect_platform_name({}, "linux", model) == "pi"
    assert detect_platform_name({}, "linux", tmp_path / "missing") == "fake"
    assert detect_platform_name({}, "darwin") == "fake"
