# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Mic -> VAD -> Whisper -> utterance events. There is no wake word: Claude decides.

Without echo cancellation the mic is muted while cadbot speaks (half-duplex). With it,
speech of about 0.4 s or more during playback counts as a barge-in.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import numpy as np

from cadbot.bus import EventBus, Snapshot, Utterance
from cadbot.platform.base import AudioIn
from cadbot.sensors.stt import SpeechToText
from cadbot.sensors.vad import SpeechDiscarded, SpeechEnd, SpeechSegmenter, SpeechStart

log = logging.getLogger(__name__)


class SpeakingState(Protocol):
    """What the listener needs to know about cadbot's own speech."""

    @property
    def speaking(self) -> bool: ...

    def recently_spoke(self, tail_s: float) -> bool: ...


@dataclass
class ListenerHooks:
    on_speech_start: Callable[[], None] = lambda: None
    on_speech_discarded: Callable[[], None] = lambda: None
    on_barge_in: Callable[[], None] = lambda: None


class Listener:
    def __init__(self, *, audio_in: AudioIn, vad: Callable[[np.ndarray], float],
                 segmenter: SpeechSegmenter, stt: SpeechToText, bus: EventBus,
                 speech_state: SpeakingState, echo_cancellation: bool,
                 half_duplex_tail_s: float = 0.3, barge_in_min_s: float = 0.4,
                 hooks: ListenerHooks | None = None,
                 snapshot: Callable[[], Snapshot | None] = lambda: None) -> None:
        self.audio_in = audio_in
        self.snapshot = snapshot
        self.vad = vad
        self.segmenter = segmenter
        self.stt = stt
        self.bus = bus
        self.speech_state = speech_state
        self.echo_cancellation = echo_cancellation
        self.tail_s = half_duplex_tail_s
        self.barge_in_min_s = barge_in_min_s
        self.hooks = hooks or ListenerHooks()
        self.enabled = True
        self._muted = False
        self._started_at = datetime.now()
        self._barged_in = False
        self._during_speech = False
        self._stt_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()

    def _should_mute(self) -> bool:
        if not self.enabled:
            return True
        return not self.echo_cancellation and self.speech_state.recently_spoke(self.tail_s)

    async def run(self) -> None:
        await self.audio_in.start()
        async for chunk in self.audio_in.chunks():
            self.process(chunk.samples)

    def process(self, frame: np.ndarray) -> None:
        if self._should_mute():
            if not self._muted:
                self._muted = True
                self.segmenter.reset()
                reset = getattr(self.vad, "reset", None)
                if reset is not None:
                    reset()
            return
        self._muted = False
        for event in self.segmenter.push(frame, self.vad(frame)):
            self._handle(event)
        self._check_barge_in()

    def _handle(self, event: SpeechStart | SpeechEnd | SpeechDiscarded) -> None:
        if isinstance(event, SpeechStart):
            self._started_at = datetime.now()
            self._barged_in = False
            self._during_speech = self.speech_state.speaking
            self.hooks.on_speech_start()
        elif isinstance(event, SpeechDiscarded):
            self.hooks.on_speech_discarded()
        else:
            task = asyncio.get_running_loop().create_task(self._transcribe(event))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def _check_barge_in(self) -> None:
        if (self.echo_cancellation and self.segmenter.active and not self._barged_in
                and self.speech_state.speaking and self.segmenter.speech_s >= self.barge_in_min_s):
            self._barged_in = True
            self._during_speech = True
            log.info("barge-in")
            self.hooks.on_barge_in()

    async def _transcribe(self, event: SpeechEnd) -> None:
        started_at, during = self._started_at, self._during_speech
        async with self._stt_lock:  # one transcription at a time, in order
            transcript = await asyncio.to_thread(self.stt.transcribe, event.audio)
        if transcript is None:
            log.info("heard speech but no words")
            self.hooks.on_speech_discarded()
            return
        log.debug("heard: %s", transcript.text)
        await self.bus.put(Utterance(
            text=transcript.text, started_at=started_at, duration_s=event.audio.size / 16_000,
            language=transcript.language, during_speech=during, snapshot=self.snapshot()))
