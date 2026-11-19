# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""cadbot's mouth, drawn under the RoboEyes eyes. Opens with the speech audio level."""

from __future__ import annotations

import math

import pygame

from cadbot.face.expressions import Mouth

# Curve depth in pixels at full intensity (positive = smile, negative = frown) and width.
_CURVES: dict[str, tuple[float, int]] = {
    "smile_slight": (4, 56), "smile": (9, 64), "smile_big": (13, 76),
    "frown": (-8, 56), "frown_soft": (-4, 48), "flat": (0, 52), "flat_soft": (0, 40),
    "closed": (0, 34),
}


def _curve_points(cx: int, cy: int, width: int, depth: float, n: int = 16) -> list[tuple[int, int]]:
    points = []
    for i in range(n + 1):
        t = i / n
        x = cx - width / 2 + t * width
        y = cy + depth * (1 - (2 * t - 1) ** 2)
        points.append((round(x), round(y)))
    return points


def draw_mouth(surface: pygame.Surface, area: pygame.Rect, shape: Mouth, *,
               open_amount: float = 0.0, intensity: float = 1.0,
               colour: tuple[int, int, int] = (90, 210, 255)) -> None:
    """Draw the mouth centred in `area`. While talking (open_amount > 0) it opens and closes."""
    cx, cy = area.centerx, area.centery
    scale = 0.4 + 0.6 * max(0.0, min(1.0, intensity))
    if open_amount > 0.05:
        height = 3 + int(open_amount * 18)
        width = 34 + int(open_amount * 10)
        pygame.draw.ellipse(surface, colour, (cx - width // 2, cy - height // 2, width, height))
        return
    if shape == "small_o":
        pygame.draw.circle(surface, colour, (cx, cy), 7, 3)
        return
    if shape == "wavy":
        points = [(round(cx - 28 + i * 3.5), round(cy + 3 * scale * math.sin(i * 0.9)))
                  for i in range(17)]
        pygame.draw.lines(surface, colour, False, points, 3)
        return
    depth, width = _CURVES[shape]
    pygame.draw.lines(surface, colour, False, _curve_points(cx, cy, width, depth * scale), 4)
