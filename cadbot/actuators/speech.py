# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Speaking: synthesise sentence by sentence, play while the next one is being made.

`stop()` silences playback at once and reports what was actually heard, so Claude can
be told exactly where it was cut off.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from cadbot.actuators.tts import Synthesizer
from cadbot.platform.base import AudioOut

log = logging.getLogger(__name__)

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_MARKDOWN = re.compile(r"[*_`#>|~]+")


def split_sentences(text: str, min_chars: int = 12) -> list[str]:
    """Split into sentences; very short fragments are joined to the next one."""
    parts = [p.strip() for p in _SENTENCE_END.split(text.strip()) if p.strip()]
    merged: list[str] = []
    for part in parts:
        if merged and len(merged[-1]) < min_chars:
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return merged


def clean_for_speech(text: str) -> str:
    """Remove markdown symbols that Piper would read out or stumble over."""
    return re.sub(r"\s+", " ", _MARKDOWN.sub("", text)).strip()


@dataclass
class SpeechResult:
    spoken: list[str] = field(default_factory=list)
    unspoken: list[str] = field(default_factory=list)
    interrupted: bool = False

    @property
    def spoken_text(self) -> str:
        return " ".join(self.spoken)

    @property
    def unspoken_text(self) -> str:
        return " ".join(self.unspoken)


class SpeechOutput:
    def __init__(self, tts: Synthesizer, audio_out: AudioOut) -> None:
        self.tts = tts
        self.audio_out = audio_out
        self._lock = asyncio.Lock()
        self._interrupted = False
        self._active = 0
        self._last_end = 0.0
        self.on_start: Callable[[], None] = lambda: None
        self.on_end: Callable[[], None] = lambda: None

    @property
    def speaking(self) -> bool:
        return self._active > 0

    def recently_spoke(self, tail_s: float) -> bool:
        """True while speaking or within `tail_s` after (half-duplex mic muting)."""
        return self.speaking or (time.monotonic() - self._last_end) < tail_s

    def level(self) -> float:
        return self.audio_out.level() if self.speaking else 0.0

    def stop(self) -> None:
        self._interrupted = True
        self.audio_out.stop()

    async def speak(self, text: str, lang: str = "en",
                    result: SpeechResult | None = None) -> SpeechResult:
        """Speak `text`. `result` is updated live, so it stays accurate even if the
        caller is cancelled half-way through."""
        result = result if result is not None else SpeechResult()
        sentences = split_sentences(clean_for_speech(text))
        result.unspoken = list(sentences)
        async with self._lock:
            self._interrupted = False
            return await self._speak(sentences, lang, result)

    async def _speak(self, sentences: list[str], lang: str,
                     result: SpeechResult) -> SpeechResult:
        if not sentences:
            return result
        self._begin()
        pending = asyncio.create_task(asyncio.to_thread(self.tts.synthesize, sentences[0], lang))
        try:
            for i, sentence in enumerate(sentences):
                audio, rate = await pending
                if i + 1 < len(sentences):
                    pending = asyncio.create_task(
                        asyncio.to_thread(self.tts.synthesize, sentences[i + 1], lang))
                if self._interrupted or not await self.audio_out.play(audio, rate):
                    break
                result.spoken.append(sentence)
                result.unspoken.pop(0)
        finally:
            if not pending.done():
                pending.cancel()
            result.interrupted = bool(result.unspoken)
            self._end()
        return result

    async def play_audio(self, audio: np.ndarray, rate: int) -> bool:
        """Play pre-rendered audio (canned clips) through the same half-duplex gate."""
        async with self._lock:
            self._interrupted = False
            self._begin()
            try:
                return await self.audio_out.play(audio, rate)
            finally:
                self._end()

    def _begin(self) -> None:
        self._active += 1
        if self._active == 1:
            self.on_start()

    def _end(self) -> None:
        self._active -= 1
        if self._active == 0:
            self._last_end = time.monotonic()
            self.on_end()
