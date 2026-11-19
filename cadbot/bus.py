# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Typed events and the queue that carries them to the agent.

Every input becomes an event; the router turns each one into a message for Claude.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Snapshot:
    """What the camera shows right now: a 640x360 JPEG plus the face readings."""

    jpeg: bytes
    taken_at: datetime
    is_night: bool
    readings: str
    """e.g. 'track 3: Priya (0.82, confident, frontal) · track 4: unknown (profile)'."""


@dataclass(frozen=True)
class Utterance:
    """One stretch of speech, transcribed locally by Whisper."""

    text: str
    started_at: datetime
    duration_s: float
    language: str = "en"
    during_speech: bool = False
    """True if the person spoke while cadbot was talking (needs echo cancellation)."""
    snapshot: Snapshot | None = None


@dataclass(frozen=True)
class Observation:
    """A camera frame worth looking at: the scene changed, a face appeared, or a heartbeat."""

    snapshot: Snapshot
    reason: str


@dataclass(frozen=True)
class BackOnline:
    """The connection to Claude is back; lists what arrived while it was down."""

    since: datetime
    missed: tuple[Utterance, ...] = ()


Event = Utterance | Observation | BackOnline


class EventBus:
    """FIFO of events. A newer observation replaces one still waiting, so a busy agent
    never works through a backlog of stale frames."""

    def __init__(self) -> None:
        self._events: deque[Event] = deque()
        self._ready = asyncio.Event()

    async def put(self, event: Event) -> None:
        self.put_nowait(event)

    def put_nowait(self, event: Event) -> None:
        if isinstance(event, Observation):
            for queued in list(self._events):
                if isinstance(queued, Observation):
                    self._events.remove(queued)
        self._events.append(event)
        self._ready.set()

    async def get(self) -> Event:
        while not self._events:
            self._ready.clear()
            await self._ready.wait()
        return self._events.popleft()

    def empty(self) -> bool:
        return not self._events

    def __len__(self) -> int:
        return len(self._events)
