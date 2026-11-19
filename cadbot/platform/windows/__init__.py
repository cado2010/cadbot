# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""The Windows development PC: USB webcam, mic and headphones, a pygame window."""

from __future__ import annotations

from cadbot.platform.base import Capabilities, Platform


def build() -> Platform:
    from cadbot.platform.windows import audio, camera, display, presence, privacy, wifi
    from cadbot.platform.windows.lifecycle import NullLifecycle
    from cadbot.platform.windows.paths import make_paths
    from cadbot.platform.windows.system import WindowsSystemInfo

    return Platform(
        name="windows",
        capabilities=Capabilities(
            night_vision=False, presence_sensor=False, privacy_switch=False,
            echo_cancellation=False, touch=False, keyboard=True, camera=True, wifi_scan=False,
        ),
        paths=make_paths(),
        system=WindowsSystemInfo(),
        lifecycle=NullLifecycle(),
        _camera=camera.make_camera,
        _audio_in=audio.make_audio_in,
        _audio_out=audio.make_audio_out,
        _display=display.make_display,
        _presence=presence.make_presence,
        _privacy=privacy.make_privacy,
        _wifi=wifi.make_wifi,
    )
