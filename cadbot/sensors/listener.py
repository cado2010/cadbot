# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Mic -> VAD -> Whisper -> utterance events. There is no wake word: Claude decides.

Without echo cancellation (PC speakers) the mic is muted for normal listening while cadbot
speaks (half-duplex), but short utterances are still checked for a stop phrase ("stop",
"never mind"...), which interrupts at once. With echo cancellation or headphones, any speech
of about 0.4 s during playback interrupts (barge-in).
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
from cadbot.sensors.stop_phrases import DEFAULT_STOP_PHRASES, match_stop_phrase
from cadbot.sensors.stt import SpeechToText
from cadbot.sensors.vad import (
    SegmenterConfig,
    SpeechDiscarded,
    SpeechEnd,
    SpeechSegmenter,
    SpeechStart,
)

log = logging.getLogger(__name__)


class SpeakingState(Protocol):
    """What the listener needs to know about cadbot's own speech."""

    @property
    def speaking(self) -> bool: ...

    def recently_spoke(self, tail_s: float) -> bool: ...

    @property
    def current_text(self) -> str:
        """What cadbot is saying right now ('' when silent)."""
        ...


@dataclass
class ListenerHooks:
    on_speech_start: Callable[[], None] = lambda: None
    on_speech_discarded: Callable[[], None] = lambda: None
    on_barge_in: Callable[[], None] = lambda: None
    on_stop_phrase: Callable[[str], None] = lambda _phrase: None


class Listener:
    def __init__(self, *, audio_in: AudioIn, vad: Callable[[np.ndarray], float],
                 segmenter: SpeechSegmenter, stt: SpeechToText, bus: EventBus,
                 speech_state: SpeakingState, echo_cancellation: bool,
                 half_duplex_tail_s: float = 0.3, barge_in_min_s: float = 0.4,
                 hooks: ListenerHooks | None = None,
                 snapshot: Callable[[], Snapshot | None] = lambda: None,
                 stop_phrases: tuple[str, ...] = DEFAULT_STOP_PHRASES,
                 stop_segmenter: SpeechSegmenter | None = None,
                 stop_stt: SpeechToText | None = None) -> None:
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
        self.stop_phrases = stop_phrases
        self.stop_stt = stop_stt  # a faster model for the stop check; None = use `stt`
        self._stop_lock = asyncio.Lock()
        # While muted for cadbot's own speech: short pieces of speech, checked for "stop".
        self._stop_segmenter = stop_segmenter or SpeechSegmenter(SegmenterConfig(
            end_silence_ms=300, min_speech_ms=150, max_utterance_s=2.5, pre_roll_ms=200))
        self._stop_started_at = datetime.now()

    MAX_STOP_SPEECH_S = 2.0

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
                self._stop_segmenter.reset()
                reset = getattr(self.vad, "reset", None)
                if reset is not None:
                    reset()
            if self.enabled and self.stop_phrases and self.speech_state.speaking:
                self._listen_for_stop(frame)
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

    # ------------------------------------------------------------------ "stop" while speaking

    def _listen_for_stop(self, frame: np.ndarray) -> None:
        for event in self._stop_segmenter.push(frame, self.vad(frame)):
            if isinstance(event, SpeechStart):
                self._stop_started_at = datetime.now()
            elif isinstance(event, SpeechEnd) and event.speech_s <= self.MAX_STOP_SPEECH_S:
                task = asyncio.get_running_loop().create_task(self._check_stop(event))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    async def _check_stop(self, event: SpeechEnd) -> None:
        """Transcribe a short piece of speech heard while talking; act only on a stop phrase."""
        started_at, speaking = self._stop_started_at, self.speech_state.current_text
        stt = self.stop_stt or self.stt
        async with self._stop_lock if self.stop_stt is not None else self._stt_lock:
            transcript = await asyncio.to_thread(stt.transcribe, event.audio)
        if transcript is None:
            return
        phrase = match_stop_phrase(transcript.text, self.stop_phrases, speaking)
        if phrase is None:
            log.debug("heard while speaking (ignored): %s", transcript.text)
            return
        log.info("stop phrase heard: %r", phrase)
        self.hooks.on_stop_phrase(transcript.text)
        await self.bus.put(Utterance(
            text=transcript.text, started_at=started_at, duration_s=event.audio.size / 16_000,
            language=transcript.language, during_speech=True, snapshot=self.snapshot()))

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
