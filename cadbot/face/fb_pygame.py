# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""A MicroPython-FrameBuffer look-alike that draws on a pygame surface, for RoboEyes."""

from __future__ import annotations

import pygame

Colour = tuple[int, int, int]


class PygameFrameBuffer:
    """Implements the drawing calls RoboEyes makes. Colour 0 is the background, 1 the eyes."""

    def __init__(self, surface: pygame.Surface, background: Colour = (8, 10, 18),
                 foreground: Colour = (90, 210, 255)) -> None:
        self.surface = surface
        self.palette: dict[int, Colour] = {0: background, 1: foreground}

    def _c(self, colour: int) -> Colour:
        return self.palette.get(colour, self.palette[1])

    def fill(self, c: int) -> None:
        self.surface.fill(self._c(c))

    def pixel(self, x: int, y: int, c: int) -> None:
        self.surface.set_at((x, y), self._c(c))

    def hline(self, x: int, y: int, w: int, c: int) -> None:
        self.fill_rect(x, y, w, 1, c)

    def vline(self, x: int, y: int, h: int, c: int) -> None:
        self.fill_rect(x, y, 1, h, c)

    def line(self, x1: int, y1: int, x2: int, y2: int, c: int) -> None:
        pygame.draw.line(self.surface, self._c(c), (x1, y1), (x2, y2))

    def rect(self, x: int, y: int, w: int, h: int, c: int, f: bool = False) -> None:
        if w > 0 and h > 0:
            pygame.draw.rect(self.surface, self._c(c), (x, y, w, h), 0 if f else 1)

    def fill_rect(self, x: int, y: int, w: int, h: int, c: int) -> None:
        self.rect(x, y, w, h, c, True)

    def ellipse(self, x: int, y: int, xr: int, yr: int, c: int, f: bool = False,
                m: int = 0xF) -> None:
        if xr > 0 and yr > 0:
            pygame.draw.ellipse(self.surface, self._c(c), (x - xr, y - yr, 2 * xr, 2 * yr),
                                0 if f else 1)

    def fill_rrect(self, x: int, y: int, w: int, h: int, r: int, c: int) -> None:
        if w <= 0 or h <= 0:
            return
        radius = max(0, min(r, w // 2, h // 2))
        pygame.draw.rect(self.surface, self._c(c), (x, y, w, h), 0, border_radius=radius)

    def fill_triangle(self, x0: int, y0: int, x1: int, y1: int, x2: int, y2: int,
                      c: int) -> None:
        pygame.draw.polygon(self.surface, self._c(c), [(x0, y0), (x1, y1), (x2, y2)])
