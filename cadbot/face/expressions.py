# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""The expressions Claude can choose, mapped to RoboEyes settings and a mouth shape.

One entry per row of the "Expressions" table in docs/cadbot-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from cadbot.vendor.roboeyes import ANGRY, CURIOUS, DEFAULT, HAPPY, NE, NW, TIRED, E, N, S, W

Mouth = Literal["smile_slight", "smile", "smile_big", "frown", "frown_soft", "flat",
                "flat_soft", "wavy", "small_o", "closed", "hmm", "wavy_small"]


@dataclass(frozen=True)
class Expression:
    mood: int
    position: int = DEFAULT
    mouth: Mouth = "smile_slight"
    idle: bool = False
    blink: tuple[int, int] = (3, 2)
    """Auto-blink interval and random variation, in whole seconds."""
    eye_scale: tuple[float, float] = (1.0, 1.0)
    """Width and height multipliers; `intensity` scales how far they move from 1."""
    right_eye_height: float = 1.0
    """Extra height for one eye only (>1: opened wider, for a quizzical look)."""
    pupil_scale: float = 1.0
    """Pupil size (>1: enlarged pupils, a natural sign of interest)."""
    anim: Literal["laugh", "confuse"] | None = None


EXPRESSIONS: dict[str, Expression] = {
    "neutral": Expression(DEFAULT, mouth="smile_slight", idle=True),
    "listening": Expression(DEFAULT, mouth="closed", eye_scale=(1.0, 1.15)),
    "thinking": Expression(DEFAULT, NW, mouth="flat"),
    # searching or interested: one eye wider, enlarged pupils glancing up and aside,
    # and a small wavy mouth (smaller and gentler than "confused")
    "curious": Expression(CURIOUS, NE, mouth="wavy_small", right_eye_height=1.18,
                          pupil_scale=1.3),
    "happy": Expression(HAPPY, mouth="smile"),
    "laughing": Expression(HAPPY, mouth="smile_big", anim="laugh"),
    "sad": Expression(TIRED, S, mouth="frown"),
    "confused": Expression(DEFAULT, mouth="wavy", anim="confuse"),
    "surprised": Expression(DEFAULT, mouth="small_o", eye_scale=(1.12, 1.25)),
    "concerned": Expression(ANGRY, mouth="flat"),
    "sleepy": Expression(TIRED, mouth="closed", blink=(6, 3)),
    "empathetic": Expression(TIRED, S, mouth="frown_soft", blink=(5, 2)),
    "calm": Expression(DEFAULT, mouth="flat_soft", blink=(5, 2), eye_scale=(0.9, 0.9)),
}

LOOKS: dict[str, int] = {"center": DEFAULT, "left": W, "right": E, "up": N, "down": S}

PRESET_MOMENTS = ("listening", "waiting", "speaking", "idle")

DEFAULT_PRESETS: dict[str, str | None] = {
    "listening": "listening",
    "waiting": "thinking",
    "speaking": None,  # keep whatever Claude chose for the reply
    "idle": "neutral",
}
