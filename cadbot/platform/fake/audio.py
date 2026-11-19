# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Fake microphone (plays scripted audio or WAV files) and fake speaker (records to memory)."""

from __future__ import annotations

import asyncio
import os
import time
import wave
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np

from cadbot.platform.base import AUDIO_SAMPLE_RATE, AudioChunk
from cadbot.platform.common.audio_math import resample, rms_level

BLOCK = 512


def read_wav(path: Path) -> np.ndarray:
    """Mono float32 at 16 kHz from a 16-bit PCM WAV file."""
    with wave.open(str(path), "rb") as wav:
        rate, channels = wav.getframerate(), wav.getnchannels()
        data = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    samples = data.reshape(-1, channels).mean(axis=1).astype(np.float32) / 32768.0
    return resample(samples, rate, AUDIO_SAMPLE_RATE)


class FakeAudioIn:
    """Yields the scripted clips in 32 ms chunks, then silence (or stops).

    With `realtime=True` chunks are paced like a real microphone.
    """

    def __init__(self, script: list[np.ndarray] | None = None, *, realtime: bool = False,
                 then_silence: bool = False) -> None:
        if script is None:
            folder = os.environ.get("CADBOT_FAKE_AUDIO_DIR")
            script = [read_wav(p) for p in sorted(Path(folder).glob("*.wav"))] if folder else []
        self._script = script
        self._realtime = realtime
        self._then_silence = then_silence
        self._running = False

    async def start(self) -> None:
        self._running = True

    async def chunks(self) -> AsyncIterator[AudioChunk]:
        for clip in self._script:
            padded = np.concatenate([clip, np.zeros((-clip.size) % BLOCK, dtype=np.float32)])
            for i in range(0, padded.size, BLOCK):
                if not self._running:
                    return
                yield AudioChunk(padded[i : i + BLOCK].astype(np.float32), time.monotonic())
                await asyncio.sleep(BLOCK / AUDIO_SAMPLE_RATE if self._realtime else 0)
        while self._running and self._then_silence:
            yield AudioChunk(np.zeros(BLOCK, dtype=np.float32), time.monotonic())
            await asyncio.sleep(BLOCK / AUDIO_SAMPLE_RATE if self._realtime else 0)

    async def stop(self) -> None:
        self._running = False


class FakeAudioOut:
    """Records what was played. `speed` = 0 finishes instantly; 1 = real time."""

    def __init__(self, speed: float | None = None) -> None:
        self.speed = float(os.environ.get("CADBOT_FAKE_AUDIO_SPEED", "0")) if speed is None \
            else speed
        self.played: list[tuple[np.ndarray, int]] = []
        self.stop_count = 0
        self._stopped = asyncio.Event()
        self._playing = 0
        self._level = 0.0

    async def start(self) -> None:
        pass

    async def play(self, samples: np.ndarray, sample_rate: int) -> bool:
        samples = np.asarray(samples, dtype=np.float32)
        self._stopped.clear()
        self._playing += 1
        self._level = rms_level(samples)
        try:
            duration = samples.size / sample_rate * self.speed
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=duration)
                return False
            except TimeoutError:
                self.played.append((samples, sample_rate))
                return True
        finally:
            self._playing -= 1
            self._level = 0.0

    def stop(self) -> None:
        self.stop_count += 1
        self._stopped.set()
        self._level = 0.0

    def level(self) -> float:
        return self._level

    @property
    def is_playing(self) -> bool:
        return self._playing > 0

    async def close(self) -> None:
        self.stop()
