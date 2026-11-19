# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Microphone and speaker through sounddevice (PortAudio): WASAPI on Windows, ALSA on the Pi."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

import numpy as np

from cadbot.platform.base import AUDIO_SAMPLE_RATE, AudioChunk
from cadbot.platform.common.audio_math import ChunkBuffer, resample, rms_level

log = logging.getLogger(__name__)

IN_BLOCK = 512  # samples at 16 kHz = 32 ms, the Silero VAD frame size
OUT_BLOCK_S = 0.02  # 20 ms output blocks keep stop() well under 200 ms


def find_device(sd: Any, name: str | None, kind: str, hostapi_prefs: list[str]) -> int | None:
    """Device index whose name contains `name`, preferring the listed host APIs.

    None means the system default device.
    """
    if not name:
        return None
    channel_key = "max_input_channels" if kind == "input" else "max_output_channels"
    hostapis = sd.query_hostapis()
    matches: list[tuple[int, int]] = []
    for index, dev in enumerate(sd.query_devices()):
        if dev[channel_key] < 1 or name.lower() not in dev["name"].lower():
            continue
        api_name = hostapis[dev["hostapi"]]["name"]
        rank = next((i for i, p in enumerate(hostapi_prefs) if p.lower() in api_name.lower()),
                    len(hostapi_prefs))
        matches.append((rank, index))
    if not matches:
        log.warning("no %s device matches %r; using the default", kind, name)
        return None
    return min(matches)[1]


def _pick_rate(sd: Any, device: int | None, kind: str, wanted: int) -> int:
    check = sd.check_input_settings if kind == "input" else sd.check_output_settings
    try:
        check(device=device, samplerate=wanted, channels=1, dtype="float32")
        return wanted
    except Exception:
        info = sd.query_devices(device, kind)
        return int(info["default_samplerate"])


class SoundDeviceAudioIn:
    def __init__(self, device_name: str | None, hostapi_prefs: list[str]) -> None:
        self._device_name = device_name
        self._prefs = hostapi_prefs
        self._queue: asyncio.Queue[AudioChunk] = asyncio.Queue(maxsize=200)
        self._stream: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._rate = AUDIO_SAMPLE_RATE
        self._blocks = ChunkBuffer(IN_BLOCK)
        self._running = False

    async def start(self) -> None:
        import sounddevice as sd

        self._loop = asyncio.get_running_loop()
        device = find_device(sd, self._device_name, "input", self._prefs)
        self._rate = _pick_rate(sd, device, "input", AUDIO_SAMPLE_RATE)
        self._stream = sd.InputStream(
            device=device, samplerate=self._rate, channels=1, dtype="float32",
            blocksize=int(self._rate * IN_BLOCK / AUDIO_SAMPLE_RATE), callback=self._callback,
        )
        self._stream.start()
        self._running = True
        log.info("mic open: device=%s rate=%d", device, self._rate)

    def _callback(self, indata: np.ndarray, frames: int, _time: Any, status: Any) -> None:
        if status:
            log.debug("mic status: %s", status)
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._push, indata[:, 0].copy())

    def _push(self, samples: np.ndarray) -> None:
        now = time.monotonic()
        for block in self._blocks.push(resample(samples, self._rate, AUDIO_SAMPLE_RATE)):
            if self._queue.full():
                self._queue.get_nowait()  # drop the oldest rather than block the audio thread
            self._queue.put_nowait(AudioChunk(block, now))

    async def chunks(self) -> AsyncIterator[AudioChunk]:
        while self._running:
            yield await self._queue.get()

    async def stop(self) -> None:
        self._running = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class _Item:
    __slots__ = ("done", "pos", "samples")

    def __init__(self, samples: np.ndarray, done: asyncio.Future[bool]) -> None:
        self.samples = samples
        self.pos = 0
        self.done = done


class SoundDeviceAudioOut:
    def __init__(self, device_name: str | None, hostapi_prefs: list[str],
                 preferred_rate: int = 22_050) -> None:
        self._device_name = device_name
        self._prefs = hostapi_prefs
        self._preferred_rate = preferred_rate
        self._rate = preferred_rate
        self._stream: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._items: deque[_Item] = deque()
        self._lock = threading.Lock()
        self._level = 0.0

    async def start(self) -> None:
        import sounddevice as sd

        self._loop = asyncio.get_running_loop()
        device = find_device(sd, self._device_name, "output", self._prefs)
        self._rate = _pick_rate(sd, device, "output", self._preferred_rate)
        self._stream = sd.OutputStream(
            device=device, samplerate=self._rate, channels=1, dtype="float32",
            blocksize=int(self._rate * OUT_BLOCK_S), latency="low", callback=self._callback,
        )
        self._stream.start()
        log.info("speaker open: device=%s rate=%d", device, self._rate)

    def _finish(self, item: _Item, completed: bool) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(_resolve, item.done, completed)

    def _callback(self, outdata: np.ndarray, frames: int, _time: Any, status: Any) -> None:
        out = outdata[:, 0]
        out.fill(0.0)
        filled = 0
        with self._lock:
            while filled < frames and self._items:
                item = self._items[0]
                take = min(frames - filled, item.samples.size - item.pos)
                out[filled : filled + take] = item.samples[item.pos : item.pos + take]
                item.pos += take
                filled += take
                if item.pos >= item.samples.size:
                    self._items.popleft()
                    self._finish(item, True)
        self._level = rms_level(out[:filled]) if filled else 0.0

    async def play(self, samples: np.ndarray, sample_rate: int) -> bool:
        if self._stream is None or self._loop is None:
            raise RuntimeError("AudioOut.start() was not called")
        data = resample(np.asarray(samples, dtype=np.float32), sample_rate, self._rate)
        done: asyncio.Future[bool] = self._loop.create_future()
        with self._lock:
            self._items.append(_Item(data, done))
        return await done

    def stop(self) -> None:
        with self._lock:
            items = list(self._items)
            self._items.clear()
        for item in items:
            self._finish(item, False)
        self._level = 0.0

    def level(self) -> float:
        return self._level

    @property
    def is_playing(self) -> bool:
        return bool(self._items)

    async def close(self) -> None:
        self.stop()
        if self._stream is not None:
            with contextlib.suppress(Exception):
                self._stream.stop()
                self._stream.close()
            self._stream = None


def _resolve(fut: asyncio.Future[bool], value: bool) -> None:
    if not fut.done():
        fut.set_result(value)
