# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Turns events into user messages for Claude. Formatting only: no decisions here."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cadbot.bus import BackOnline, Event, Utterance


def spoken_time(moment: datetime) -> str:
    hour = moment.strftime("%I").lstrip("0")
    return f"{moment.strftime('%a %d %b %Y')}, {hour}:{moment.strftime('%M %p').lower()}"


def _utterance_line(event: Utterance) -> str:
    extra = ", while you were speaking" if event.during_speech else ""
    return (f"[utterance at {spoken_time(event.started_at)}] Heard "
            f"({event.duration_s:.1f} s{extra}): \"{event.text}\"")


def render_event(event: Event, notes: list[str] | None = None) -> list[dict[str, Any]]:
    lines = list(notes or [])
    if isinstance(event, Utterance):
        lines.append(_utterance_line(event))
    elif isinstance(event, BackOnline):
        lines.append(f"[back_online at {spoken_time(datetime.now())}] The connection to Claude "
                     f"is back; it was down since {spoken_time(event.since)}.")
        if event.missed:
            lines.append("While it was down the device played its offline message and heard:")
            lines.extend(f"- {_utterance_line(u)}" for u in event.missed)
            lines.append("Decide whether any of it still needs an answer.")
    else:  # pragma: no cover - every event type must be handled above
        raise TypeError(f"no renderer for {type(event).__name__}")
    return [{"type": "text", "text": "\n".join(lines)}]
