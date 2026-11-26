# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""cadbot's mouth, drawn under the RoboEyes eyes. Opens with the speech audio level.

Sizes are in the same small logical units as RoboEyes and multiplied by `scale`, with
anti-aliased strokes so the mouth is as smooth as the eyes.
"""

from __future__ import annotations

import math

import pygame

from cadbot.face.expressions import Mouth
from cadbot.face.fb_pygame import fill_rounded_rect

Colour = tuple[int, int, int]

# Curve depth (positive = smile, negative = frown) and width, in logical units.
_CURVES: dict[str, tuple[float, int]] = {
    "smile_slight": (4, 44), "smile": (9, 54), "smile_big": (13, 64),
    "frown": (-8, 46), "frown_soft": (-4, 40), "flat": (0, 42), "flat_soft": (0, 32),
    "closed": (0, 26),
}
STROKE = 3.5  # logical units


def _stroke(surface: pygame.Surface, colour: Colour, points: list[tuple[float, float]],
            width: int) -> None:
    """A thick polyline drawn as one ribbon polygon, with smooth edges and round caps."""
    half = width / 2
    left: list[tuple[float, float]] = []
    right: list[tuple[float, float]] = []
    for i, (x, y) in enumerate(points):
        ax, ay = points[max(0, i - 1)]
        bx, by = points[min(len(points) - 1, i + 1)]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length * half, dx / length * half
        left.append((x + nx, y + ny))
        right.append((x - nx, y - ny))
    outline = left + right[::-1]
    pygame.draw.polygon(surface, colour, outline)
    pygame.draw.aalines(surface, colour, True, outline)
    for x, y in (points[0], points[-1]):
        pygame.draw.aacircle(surface, colour, (round(x), round(y)), max(1, round(half)))


def _curve(cx: float, cy: float, width: float, depth: float,
           n: int = 24) -> list[tuple[float, float]]:
    return [(cx - width / 2 + t * width, cy + depth * (1 - (2 * t - 1) ** 2))
            for t in (i / n for i in range(n + 1))]


def draw_mouth(surface: pygame.Surface, centre: tuple[int, int], shape: Mouth, *,
               open_amount: float = 0.0, intensity: float = 1.0, scale: int = 1,
               colour: Colour = (90, 210, 255)) -> None:
    """Draw the mouth centred at `centre` (screen pixels). Opens while talking."""
    cx, cy = centre
    s = scale
    width = max(2, round(STROKE * s))
    strength = 0.4 + 0.6 * max(0.0, min(1.0, intensity))
    if open_amount > 0.05:
        h = round((4 + open_amount * 16) * s)
        w = round((30 + open_amount * 8) * s)
        fill_rounded_rect(surface, colour, pygame.Rect(cx - w // 2, cy - h // 2, w, h), h // 2)
        return
    if shape == "small_o":
        pygame.draw.aacircle(surface, colour, (cx, cy), round(6 * s), width)
        return
    if shape == "hmm":  # a lopsided half-smile, one corner up: "hmm, let me see"
        points = [(cx + (-20 + t * 40) * s,
                   cy + (2.5 * (1 - (2 * t - 1) ** 2) - 5 * t) * s * strength)
                  for t in (i / 24 for i in range(25))]
        _stroke(surface, colour, points, width)
        return
    if shape == "wavy_small":  # a short, gentle wave: curious, mulling something over
        points = [(cx + (i - 8) * 1.6 * s, cy + 1.6 * s * strength * math.sin(i * 0.8))
                  for i in range(17)]
        _stroke(surface, colour, points, width)
        return
    if shape == "wavy":
        points = [(cx + (i - 12) * 2.2 * s, cy + 2.5 * s * strength * math.sin(i * 0.8))
                  for i in range(25)]
        _stroke(surface, colour, points, width)
        return
    depth, w = _CURVES[shape]
    _stroke(surface, colour, _curve(cx, cy, w * s, depth * s * strength), width)
