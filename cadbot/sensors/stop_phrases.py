# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Spoken stop commands ("stop", "never mind"...) that interrupt cadbot while it talks.

Like the Esc key, this is part of interrupting in the first half-second (design: "Interrupting
cadbot"): code stops the speech at once; Claude then hears what was said and decides what to
do. Only short utterances that are nothing but a stop phrase count, so ordinary talk (or
cadbot's own voice heard through speakers) doesn't trigger it.
"""

from __future__ import annotations

import re

DEFAULT_STOP_PHRASES = (
    "stop", "stop it", "stop talking", "stop please", "please stop",
    "never mind", "nevermind", "forget it",
    "cancel", "cancel that",
    "quiet", "be quiet", "shush", "shut up", "hush",
    "enough", "that's enough", "thats enough", "that is enough",
    "hold on", "hang on", "wait", "wait a second", "pause",
    "okay stop", "ok stop", "no stop", "no no",
)

# Words people add around a command that don't change it.
_FILLER = {"cadbot", "please", "hey", "oh", "um", "uh", "just", "ok", "okay", "alright", "so"}
_WORD = re.compile(r"[a-z']+")
MAX_WORDS = 5


def normalise(text: str) -> str:
    return " ".join(_WORD.findall(text.lower().replace("’", "'")))


def _core(text: str) -> str:
    words = normalise(text).split()
    kept = [w for w in words if w not in _FILLER]
    return " ".join(kept or words)


def match_stop_phrase(text: str, phrases: tuple[str, ...] = DEFAULT_STOP_PHRASES,
                      speaking: str = "") -> str | None:
    """The stop phrase this utterance is, or None.

    `speaking` is what cadbot is saying right now: a phrase it is itself saying doesn't
    count (it may be hearing its own voice through the speakers).
    """
    words = normalise(text).split()
    if not words or len(words) > MAX_WORDS:
        return None
    candidates = (_core(text), normalise(text))
    said = f" {normalise(speaking)} "
    ordered = sorted({normalise(p) for p in phrases}, key=lambda p: (-len(p), p))
    exact = [p for p in ordered if p in candidates]  # "stop it" for "OK, stop it please"
    prefix = [p for p in ordered if any(c.startswith(p + " ") for c in candidates)]
    matches = exact or prefix
    if not matches or f" {matches[0]} " in said:
        return None
    return matches[0]
