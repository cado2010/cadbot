# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Pi audio: the USB speakerphone through sounddevice on PipeWire/ALSA.

UNTESTED: written before the Raspberry Pi hardware arrived. Verify with `pytest -m hardware`.
"""

from __future__ import annotations

from cadbot.platform.common.sd_audio import SoundDeviceAudioIn, SoundDeviceAudioOut

HOSTAPI_PREFS = ["ALSA", "PulseAudio", "JACK"]


def make_audio_in(device: str | None) -> SoundDeviceAudioIn:
    return SoundDeviceAudioIn(device, HOSTAPI_PREFS)


def make_audio_out(device: str | None) -> SoundDeviceAudioOut:
    return SoundDeviceAudioOut(device, HOSTAPI_PREFS)
