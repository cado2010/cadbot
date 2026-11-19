# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Turns events into user messages for Claude. Formatting only: no decisions here."""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cadbot.bus import BackOnline, Event, LocationChanged, Observation, Snapshot, Utterance

_tz: ZoneInfo | None = None


def set_timezone(name: str | None) -> None:
    """Show times in the device's local timezone (from its location)."""
    global _tz
    try:
        _tz = ZoneInfo(name) if name else None
    except (ZoneInfoNotFoundError, ValueError):
        _tz = None


def spoken_time(moment: datetime) -> str:
    if _tz is not None:
        moment = (moment if moment.tzinfo else moment.astimezone()).astimezone(_tz)
    hour = moment.strftime("%I").lstrip("0")
    return f"{moment.strftime('%a %d %b %Y')}, {hour}:{moment.strftime('%M %p').lower()}"


def _utterance_line(event: Utterance) -> str:
    extra = ", while you were speaking" if event.during_speech else ""
    return (f"[utterance at {spoken_time(event.started_at)}] Heard "
            f"({event.duration_s:.1f} s{extra}): \"{event.text}\"")


def _image_block(snapshot: Snapshot) -> dict[str, Any]:
    assert snapshot.jpeg is not None
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(snapshot.jpeg).decode()}}


def _camera_line(snapshot: Snapshot) -> str:
    night = " Night vision (infrared, black and white)." if snapshot.is_night else ""
    return f"Camera ({spoken_time(snapshot.taken_at)}):{night} Faces: {snapshot.readings}"


def render_event(event: Event, notes: list[str] | None = None,
                 place: str | None = None) -> list[dict[str, Any]]:
    lines = list(notes or [])
    snapshot: Snapshot | None = None
    if isinstance(event, Utterance):
        lines.append(_utterance_line(event))
        snapshot = event.snapshot
    elif isinstance(event, Observation):
        snapshot = event.snapshot
        lines.append(f"[observation at {spoken_time(snapshot.taken_at)}] Why this frame: "
                     f"{event.reason}.")
    elif isinstance(event, BackOnline):
        lines.append(f"[back_online at {spoken_time(datetime.now())}] The connection to Claude "
                     f"is back; it was down since {spoken_time(event.since)}.")
        if event.missed:
            lines.append("While it was down the device played its offline message and heard:")
            lines.extend(f"- {_utterance_line(u)}" for u in event.missed)
            lines.append("Decide whether any of it still needs an answer.")
    elif isinstance(event, LocationChanged):
        lines.append(f"[location_changed at {spoken_time(datetime.now())}] The device seems to "
                     f"have moved from {event.previous} to {event.current} (about "
                     f"{event.distance_km:.0f} km). Mention it only if it matters.")
    else:  # pragma: no cover - every event type must be handled above
        raise TypeError(f"no renderer for {type(event).__name__}")
    if place:
        lines.append(f"Location: {place}.")
    content: list[dict[str, Any]] = []
    if snapshot is not None:
        if snapshot.jpeg is not None:
            content.append(_image_block(snapshot))
        lines.append(_camera_line(snapshot))
    content.append({"type": "text", "text": "\n".join(lines)})
    return content
