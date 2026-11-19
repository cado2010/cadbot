# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Fake hardware for tests and CI: scripted media, offscreen display, temporary folders.

The fake platform never reads .env, so tests can't pick up a real API key by accident.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from cadbot.platform.base import Capabilities, Platform, not_implemented
from cadbot.platform.common.paths import DirPaths


class FakeSystemInfo:
    def cpu_temperature_c(self) -> float | None:
        return 45.0

    def cpu_load(self) -> float:
        return 0.1

    def model_name(self) -> str:
        return "Fake test machine"


class FakeLifecycle:
    def __init__(self) -> None:
        self.events: list[str] = []

    def notify_ready(self) -> None:
        self.events.append("ready")

    def watchdog_ping(self) -> None:
        self.events.append("watchdog")

    def notify_stopping(self) -> None:
        self.events.append("stopping")


def make_paths() -> DirPaths:
    root = Path(os.environ.get("CADBOT_DATA_DIR") or tempfile.mkdtemp(prefix="cadbot-fake-"))
    return DirPaths(data_dir=root, config_dir=root / "config", cache_dir=root / "cache",
                    secrets_file=None, use_keyring=False)


def _stub(interface: str):  # type: ignore[no-untyped-def]
    def make():  # type: ignore[no-untyped-def]
        raise not_implemented("fake", interface, "a later milestone")
    return make


def build() -> Platform:
    from cadbot.platform.fake.audio import FakeAudioIn, FakeAudioOut
    from cadbot.platform.fake.camera import make_camera
    from cadbot.platform.fake.display import make_display

    return Platform(
        name="fake",
        capabilities=Capabilities(keyboard=True, camera=True),
        paths=make_paths(),
        system=FakeSystemInfo(),
        lifecycle=FakeLifecycle(),
        _camera=make_camera,
        _audio_in=lambda _device: FakeAudioIn(realtime=True, then_silence=True),
        _audio_out=lambda _device: FakeAudioOut(),
        _display=make_display,
        _presence=_stub("PresenceSensor"),
        _privacy=_stub("PrivacySwitch"),
        _wifi=_stub("WifiScanner"),
    )
