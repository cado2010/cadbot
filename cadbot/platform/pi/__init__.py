# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Raspberry Pi 5: Arducam, USB speakerphone, Touch Display 2, LD2410C, systemd.

UNTESTED: written before the Raspberry Pi hardware arrived. Verify with `pytest -m hardware`.
"""

from __future__ import annotations

from cadbot.platform.base import Capabilities, Platform


def build() -> Platform:
    from cadbot.platform.pi import audio, camera, display, presence, privacy, wifi
    from cadbot.platform.pi.lifecycle import SystemdLifecycle
    from cadbot.platform.pi.paths import make_paths
    from cadbot.platform.pi.system import PiSystemInfo

    return Platform(
        name="pi",
        capabilities=Capabilities(
            night_vision=True, presence_sensor=True, privacy_switch=True,
            echo_cancellation=True, touch=True, keyboard=False, camera=True, wifi_scan=True,
        ),
        paths=make_paths(),
        system=PiSystemInfo(),
        lifecycle=SystemdLifecycle(),
        _camera=camera.make_camera,
        _audio_in=audio.make_audio_in,
        _audio_out=audio.make_audio_out,
        _display=display.make_display,
        _presence=presence.make_presence,
        _privacy=privacy.make_privacy,
        _wifi=wifi.make_wifi,
    )
