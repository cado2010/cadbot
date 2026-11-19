# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Typed events and the queue that carries them to the agent.

Every input becomes an event; the router turns each one into a message for Claude.
Later milestones add observation, timer, email and calendar events here.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Utterance:
    """One stretch of speech, transcribed locally by Whisper."""

    text: str
    started_at: datetime
    duration_s: float
    language: str = "en"
    during_speech: bool = False
    """True if the person spoke while cadbot was talking (needs echo cancellation)."""


@dataclass(frozen=True)
class BackOnline:
    """The connection to Claude is back; lists what arrived while it was down."""

    since: datetime
    missed: tuple[Utterance, ...] = ()


Event = Utterance | BackOnline


@dataclass
class EventBus:
    queue: asyncio.Queue[Event] = field(default_factory=asyncio.Queue)

    async def put(self, event: Event) -> None:
        await self.queue.put(event)

    async def get(self) -> Event:
        return await self.queue.get()
