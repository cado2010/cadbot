# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""The face window: pygame display setup and input events.

pygame.display and pygame.event are used only here; the face renderer just draws on
the LOGICAL_SCREEN surface this class hands out.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pygame

from cadbot.platform.base import LOGICAL_SCREEN, InputEvent

log = logging.getLogger(__name__)


class PygameDisplay:
    def __init__(self, *, fullscreen: bool, video_driver: str | None = None,
                 window_size: tuple[int, int] = LOGICAL_SCREEN, hide_cursor: bool = False,
                 title: str = "cadbot") -> None:
        self._fullscreen = fullscreen
        self._driver = video_driver
        self._window_size = window_size
        self._hide_cursor = hide_cursor
        self._title = title
        self._window: pygame.Surface | None = None
        self._surface = pygame.Surface(LOGICAL_SCREEN)
        self._dest = pygame.Rect((0, 0), LOGICAL_SCREEN)
        self._injected: list[InputEvent] = []

    def open(self) -> None:
        if self._driver:
            os.environ["SDL_VIDEODRIVER"] = self._driver
        pygame.display.init()
        pygame.font.init()
        flags = pygame.FULLSCREEN if self._fullscreen else pygame.RESIZABLE
        size = (0, 0) if self._fullscreen else self._window_size
        self._window = pygame.display.set_mode(size, flags)
        pygame.display.set_caption(self._title)
        if self._hide_cursor:
            pygame.mouse.set_visible(False)
        log.info("display open: %sx%s (%s)", *self._window.get_size(),
                 pygame.display.get_driver())

    @property
    def surface(self) -> pygame.Surface:
        return self._surface

    def present(self) -> None:
        if self._window is None:
            return
        win_w, win_h = self._window.get_size()
        if (win_w, win_h) == LOGICAL_SCREEN:
            self._dest = pygame.Rect((0, 0), LOGICAL_SCREEN)
            self._window.blit(self._surface, (0, 0))
        else:  # letterbox, keeping 16:9
            scale = min(win_w / LOGICAL_SCREEN[0], win_h / LOGICAL_SCREEN[1])
            size = (max(1, int(LOGICAL_SCREEN[0] * scale)), max(1, int(LOGICAL_SCREEN[1] * scale)))
            self._dest = pygame.Rect(((win_w - size[0]) // 2, (win_h - size[1]) // 2), size)
            self._window.fill((0, 0, 0))
            self._window.blit(pygame.transform.smoothscale(self._surface, size), self._dest)
        pygame.display.flip()

    def _to_logical(self, x: float, y: float) -> tuple[int, int]:
        lx = (x - self._dest.x) * LOGICAL_SCREEN[0] / max(1, self._dest.w)
        ly = (y - self._dest.y) * LOGICAL_SCREEN[1] / max(1, self._dest.h)
        return int(lx), int(ly)

    def poll_events(self) -> list[InputEvent]:
        events, self._injected = self._injected, []
        if self._window is None:
            return events
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                events.append(InputEvent("quit"))
            elif e.type == pygame.KEYDOWN:
                events.append(InputEvent("key", key=pygame.key.name(e.key)))
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                events.append(InputEvent("pointer_down", pos=self._to_logical(*e.pos)))
            elif e.type == pygame.FINGERDOWN:
                w, h = self._window.get_size()
                events.append(InputEvent("pointer_down", pos=self._to_logical(e.x * w, e.y * h)))
        return events

    def inject(self, event: InputEvent) -> None:
        """Queue a synthetic input (tests and self-tests)."""
        self._injected.append(event)

    def save_screenshot(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        pygame.image.save(self._surface, str(path))
        return path

    def close(self) -> None:
        if self._window is not None:
            pygame.display.quit()
            self._window = None
