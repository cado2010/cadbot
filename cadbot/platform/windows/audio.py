# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Windows audio: sounddevice, preferring WASAPI devices when a device is named."""

from __future__ import annotations

from cadbot.platform.common.sd_audio import SoundDeviceAudioIn, SoundDeviceAudioOut

HOSTAPI_PREFS = ["WASAPI", "DirectSound", "MME"]


def make_audio_in(device: str | None) -> SoundDeviceAudioIn:
    return SoundDeviceAudioIn(device, HOSTAPI_PREFS)


def make_audio_out(device: str | None) -> SoundDeviceAudioOut:
    return SoundDeviceAudioOut(device, HOSTAPI_PREFS)
