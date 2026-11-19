# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""One contract for every platform implementation.

Runs against whichever platform is selected: the fake one by default (and in CI), the real
ones by hand on each machine:  CADBOT_PLATFORM=windows uv run pytest -m hardware
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from cadbot.platform import AUDIO_SAMPLE_RATE, LOGICAL_SCREEN, get_platform
from cadbot.platform.base import (
    AudioIn,
    AudioOut,
    Camera,
    Capabilities,
    Display,
    Frame,
    InputEvent,
    Lifecycle,
    Paths,
    SystemInfo,
    WifiAP,
)

PLATFORM = get_platform()
pytestmark = [] if PLATFORM.name == "fake" else [pytest.mark.hardware]


def test_capabilities() -> None:
    assert isinstance(PLATFORM.capabilities, Capabilities)
    assert all(isinstance(line, str) for line in PLATFORM.capabilities.describe())


def test_camera_returns_frames() -> None:
    camera = PLATFORM.camera()
    assert isinstance(camera, Camera)
    camera.open()
    try:
        frame = next((f for _ in range(30) if (f := camera.read()) is not None), None)
    finally:
        camera.close()
    assert isinstance(frame, Frame)
    assert frame.image.ndim == 3 and frame.image.shape[2] == 3
    assert frame.image.dtype == np.uint8
    assert isinstance(frame.is_night, bool)


async def test_audio_in_yields_16k_mono_float32() -> None:
    mic = PLATFORM.audio_in(None)
    assert isinstance(mic, AudioIn)
    if PLATFORM.name == "fake":
        from cadbot.platform.fake.audio import FakeAudioIn

        mic = FakeAudioIn([np.zeros(2000, dtype=np.float32)])
    await mic.start()
    try:
        async with asyncio.timeout(5):
            chunk = await anext(aiter(mic.chunks()))
    finally:
        await mic.stop()
    assert chunk.sample_rate == AUDIO_SAMPLE_RATE
    assert chunk.samples.dtype == np.float32 and chunk.samples.ndim == 1


async def test_audio_out_plays_and_stops_quickly() -> None:
    speaker = PLATFORM.audio_out(None)
    assert isinstance(speaker, AudioOut)
    await speaker.start()
    try:
        tone = (0.05 * np.sin(np.arange(16_000) / 8)).astype(np.float32)
        assert await speaker.play(tone[:1600], 16_000) is True
        playing = asyncio.create_task(speaker.play(tone, 16_000))
        await asyncio.sleep(0.05)
        loop = asyncio.get_running_loop()
        stopped_at = loop.time()
        speaker.stop()
        finished = await asyncio.wait_for(playing, 1.0)
        assert loop.time() - stopped_at < 0.2  # design target: audio stops within 200 ms
        assert finished in (True, False)
        assert 0.0 <= speaker.level() <= 1.0
    finally:
        await speaker.close()


def test_display_surface_and_events() -> None:
    display = PLATFORM.display()
    assert isinstance(display, Display)
    display.open()
    try:
        assert display.surface.get_size() == LOGICAL_SCREEN
        display.surface.fill((10, 20, 30))
        display.present()
        events = display.poll_events()
        assert all(isinstance(e, InputEvent) for e in events)
    finally:
        display.close()


def test_system_info() -> None:
    assert isinstance(PLATFORM.system, SystemInfo)
    temp = PLATFORM.system.cpu_temperature_c()
    assert temp is None or 0 < temp < 120
    assert PLATFORM.system.cpu_load() >= 0
    assert PLATFORM.system.model_name()


def test_paths() -> None:
    paths = PLATFORM.paths
    assert isinstance(paths, Paths)
    for folder in (paths.data_dir, paths.cache_dir, paths.models_dir, paths.logs_dir):
        assert folder.is_dir()
    assert paths.get_secret("CADBOT_TEST_SECRET_THAT_DOES_NOT_EXIST") is None


def test_lifecycle_calls_are_safe() -> None:
    assert isinstance(PLATFORM.lifecycle, Lifecycle)
    PLATFORM.lifecycle.notify_ready()
    PLATFORM.lifecycle.watchdog_ping()
    PLATFORM.lifecycle.notify_stopping()


def test_wifi_scan_returns_access_points() -> None:
    if not PLATFORM.capabilities.wifi_scan:
        pytest.skip("no Wi-Fi scanning on this platform")
    aps = PLATFORM.wifi_scanner().scan()
    assert all(isinstance(ap, WifiAP) and -110 <= ap.rssi_dbm <= 0 for ap in aps)


@pytest.mark.parametrize("factory", ["presence_sensor", "privacy_switch", "wifi_scanner"])
def test_later_interfaces_fail_clearly_or_work(factory: str) -> None:
    flag = {"presence_sensor": "presence_sensor", "privacy_switch": "privacy_switch",
            "wifi_scanner": "wifi_scan"}[factory]
    if getattr(PLATFORM.capabilities, flag):
        pytest.skip("implemented on this platform; covered by hardware checks")
    with pytest.raises(NotImplementedError, match="not implemented"):
        getattr(PLATFORM, factory)()
