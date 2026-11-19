# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Canned spoken messages for when Claude can't be reached. Fixed in code by design.

They are rendered with Piper at startup, so they play instantly even with no network.
"""

from __future__ import annotations

import asyncio
import logging
import time

import numpy as np

from cadbot.actuators.speech import SpeechOutput
from cadbot.actuators.tts import Synthesizer

log = logging.getLogger(__name__)

CANNED: dict[str, str] = {
    "offline": "Sorry, I can't reach the internet right now. "
               "I'll be back as soon as the connection returns.",
    "claude_unreachable": "I'm online, but I can't reach Claude right now. "
                          "Please try again in a few minutes.",
    "overloaded": "Claude is very busy right now. Please ask me again in a minute.",
    "rate_limit": "I've hit my request limit for the moment. Give me a minute and try again.",
    "server_error": "Claude's service had an error on its side. Please try again shortly.",
    "budget": "I've run out of my API budget, so I can't answer until it's topped up.",
    "auth": "I can't sign in to Claude. My API key needs checking.",
    "permission": "My account isn't allowed to use that model. The setup needs fixing.",
    "too_large": "That was too much for me to handle at once. "
                 "Let me start fresh; could you ask again?",
    "bad_request": "Something went wrong with how I asked Claude. "
                   "I've logged it; please try again.",
    "unknown": "Something went wrong reaching Claude. I've logged the details.",
    "one_moment": "One moment.",
}


class CannedClips:
    def __init__(self, tts: Synthesizer, speech: SpeechOutput, min_interval_s: float = 60.0,
                 lang: str = "en") -> None:
        self.tts = tts
        self.speech = speech
        self.min_interval_s = min_interval_s
        self.lang = lang
        self._audio: dict[str, tuple[np.ndarray, int]] = {}
        self._last_played: dict[str, float] = {}

    async def render_all(self) -> None:
        for key, text in CANNED.items():
            if key not in self._audio:
                self._audio[key] = await asyncio.to_thread(self.tts.synthesize, text, self.lang)
        log.info("canned clips ready (%d)", len(self._audio))

    async def play(self, key: str, *, rate_limited: bool = True) -> bool:
        """Play a clip; skipped if the same one played within the last minute."""
        now = time.monotonic()
        if rate_limited and now - self._last_played.get(key, -1e9) < self.min_interval_s:
            log.info("canned %r skipped (played recently)", key)
            return False
        self._last_played[key] = now
        if key not in self._audio:
            self._audio[key] = await asyncio.to_thread(self.tts.synthesize, CANNED[key], self.lang)
        audio, rate = self._audio[key]
        return await self.speech.play_audio(audio, rate)
