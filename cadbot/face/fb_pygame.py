# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""A MicroPython-FrameBuffer look-alike that draws on a pygame surface, for RoboEyes.

RoboEyes works in a small logical space (sized for tiny OLED screens). This adapter
multiplies every coordinate by `scale` and draws at full resolution with anti-aliased
edges, so the eyes stay smooth on a 1280x720 screen instead of being pixel-blown-up.
"""

from __future__ import annotations

import pygame

Colour = tuple[int, int, int]


def fill_rounded_rect(surface: pygame.Surface, colour: Colour, rect: pygame.Rect,
                      radius: int) -> None:
    """Filled rounded rectangle with anti-aliased corners."""
    if rect.w <= 0 or rect.h <= 0:
        return
    r = max(0, min(radius, rect.w // 2, rect.h // 2))
    if r < 2:
        pygame.draw.rect(surface, colour, rect)
        return
    pygame.draw.rect(surface, colour, (rect.x + r, rect.y, rect.w - 2 * r, rect.h))
    pygame.draw.rect(surface, colour, (rect.x, rect.y + r, rect.w, rect.h - 2 * r))
    left, right = rect.x + r, rect.right - r - 1
    top, bottom = rect.y + r, rect.bottom - r - 1
    pygame.draw.aacircle(surface, colour, (left, top), r, draw_top_left=True)
    pygame.draw.aacircle(surface, colour, (right, top), r, draw_top_right=True)
    pygame.draw.aacircle(surface, colour, (left, bottom), r, draw_bottom_left=True)
    pygame.draw.aacircle(surface, colour, (right, bottom), r, draw_bottom_right=True)


class PygameFrameBuffer:
    """Implements the drawing calls RoboEyes makes. Colour 0 is the background, 1 the eyes."""

    def __init__(self, surface: pygame.Surface, background: Colour = (8, 10, 18),
                 foreground: Colour = (90, 210, 255), scale: int = 1) -> None:
        self.surface = surface
        self.scale = scale
        self.palette: dict[int, Colour] = {0: background, 1: foreground}

    def _c(self, colour: int) -> Colour:
        return self.palette.get(colour, self.palette[1])

    def _r(self, x: int, y: int, w: int, h: int) -> pygame.Rect:
        s = self.scale
        return pygame.Rect(x * s, y * s, w * s, h * s)

    def fill(self, c: int) -> None:
        self.surface.fill(self._c(c))

    def pixel(self, x: int, y: int, c: int) -> None:
        self.fill_rect(x, y, 1, 1, c)

    def hline(self, x: int, y: int, w: int, c: int) -> None:
        self.fill_rect(x, y, w, 1, c)

    def vline(self, x: int, y: int, h: int, c: int) -> None:
        self.fill_rect(x, y, 1, h, c)

    def line(self, x1: int, y1: int, x2: int, y2: int, c: int) -> None:
        s = self.scale
        pygame.draw.aaline(self.surface, self._c(c), (x1 * s, y1 * s), (x2 * s, y2 * s),
                           max(1, s))

    def rect(self, x: int, y: int, w: int, h: int, c: int, f: bool = False) -> None:
        if w > 0 and h > 0:
            pygame.draw.rect(self.surface, self._c(c), self._r(x, y, w, h),
                             0 if f else max(1, self.scale))

    def fill_rect(self, x: int, y: int, w: int, h: int, c: int) -> None:
        self.rect(x, y, w, h, c, True)

    def ellipse(self, x: int, y: int, xr: int, yr: int, c: int, f: bool = False,
                m: int = 0xF) -> None:
        if xr > 0 and yr > 0:
            pygame.draw.ellipse(self.surface, self._c(c), self._r(x - xr, y - yr, 2 * xr, 2 * yr),
                                0 if f else max(1, self.scale))

    def fill_rrect(self, x: int, y: int, w: int, h: int, r: int, c: int) -> None:
        fill_rounded_rect(self.surface, self._c(c), self._r(x, y, w, h), r * self.scale)

    def fill_triangle(self, x0: int, y0: int, x1: int, y1: int, x2: int, y2: int,
                      c: int) -> None:
        s = self.scale
        points = [(x0 * s, y0 * s), (x1 * s, y1 * s), (x2 * s, y2 * s)]
        colour = self._c(c)
        pygame.draw.polygon(self.surface, colour, points)
        pygame.draw.aalines(self.surface, colour, True, points)
