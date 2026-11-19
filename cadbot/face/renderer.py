# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Draws the face in the Display. Animation only: Claude chooses every expression.

RoboEyes draws the eyes on a small 320x180 surface (top 140 px); cadbot draws the mouth
below and scales the result to the 1280x720 display, then adds the stop button and icons.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import pygame

from cadbot.face.expressions import DEFAULT_PRESETS, EXPRESSIONS, LOOKS, Expression
from cadbot.face.fb_pygame import PygameFrameBuffer
from cadbot.face.mouth import draw_mouth
from cadbot.platform.base import LOGICAL_SCREEN, Display, InputEvent
from cadbot.vendor.roboeyes import OFF, ON, RoboEyes

log = logging.getLogger(__name__)

SMALL = (320, 180)
EYE_AREA = pygame.Rect(0, 0, 320, 140)
MOUTH_AREA = pygame.Rect(0, 140, 320, 40)
BASE_EYE = {"width": 72, "height": 72, "radius": 16, "spacing": 28}
STOP_BUTTON = pygame.Rect(1090, 600, 160, 80)
ACCENT = (90, 210, 255)
BACKGROUND = (8, 10, 18)


@dataclass
class FaceCallbacks:
    on_stop: Callable[[], None] = lambda: None
    on_quit: Callable[[], None] = lambda: None


@dataclass
class FaceState:
    expression: str = "neutral"
    intensity: float = 1.0
    look: str | None = None
    show_stop: bool = False
    status: str | None = None  # "offline" shows the no-Wi-Fi icon
    presets: dict[str, str | None] = field(default_factory=lambda: dict(DEFAULT_PRESETS))


class Face:
    def __init__(self, display: Display, level: Callable[[], float] = lambda: 0.0,
                 fps: int = 30, callbacks: FaceCallbacks | None = None) -> None:
        self.display = display
        self.level = level
        self.fps = fps
        self.callbacks = callbacks or FaceCallbacks()
        self.state = FaceState()
        self._small = pygame.Surface(SMALL)
        self.fb = PygameFrameBuffer(self._small.subsurface(EYE_AREA), BACKGROUND, ACCENT)
        self.eyes = RoboEyes(self.fb, EYE_AREA.w, EYE_AREA.h, frame_rate=fps,
                             on_show=self._on_show)
        self.eyes.eyes_radius(BASE_EYE["radius"], BASE_EYE["radius"])
        self.eyes.eyes_spacing(BASE_EYE["spacing"])
        self.eyes.open()
        self._font: pygame.font.Font | None = None
        self._running = False
        self._version = 0
        self.set("neutral")

    # ----------------------------------------------------------------- what Claude controls

    def set(self, expression: str, intensity: float = 1.0, look: str | None = None) -> None:
        if expression not in EXPRESSIONS:
            raise ValueError(f"unknown expression {expression!r}")
        if look is not None and look not in LOOKS:
            raise ValueError(f"unknown look {look!r}")
        self._version += 1
        spec = EXPRESSIONS[expression]
        intensity = max(0.0, min(1.0, intensity))
        self.state.expression, self.state.intensity, self.state.look = expression, intensity, look
        self._apply(spec, intensity, look)

    def set_presets(self, presets: dict[str, str | None]) -> None:
        for moment, expression in presets.items():
            if moment not in self.state.presets:
                raise ValueError(f"unknown preset moment {moment!r}")
            if expression is not None and expression not in EXPRESSIONS:
                raise ValueError(f"unknown expression {expression!r}")
            self.state.presets[moment] = expression

    def apply_preset(self, moment: str) -> None:
        """Apply Claude's preset for this moment (listening, waiting, speaking, idle)."""
        expression = self.state.presets.get(moment)
        if expression:
            self.set(expression)

    def schedule_preset(self, moment: str, delay_s: float) -> None:
        """Apply a preset later, unless the expression changes before then."""
        version = self._version

        def apply() -> None:
            if self._version == version:
                self.apply_preset(moment)

        asyncio.get_running_loop().call_later(delay_s, apply)

    # ----------------------------------------------------------------- local display state

    def set_busy(self, busy: bool) -> None:
        """Show the stop button while cadbot is thinking or speaking."""
        self.state.show_stop = busy

    def set_status(self, status: str | None) -> None:
        self.state.status = status

    # ----------------------------------------------------------------- animation

    def _apply(self, spec: Expression, intensity: float, look: str | None) -> None:
        sx = 1 + (spec.eye_scale[0] - 1) * intensity
        sy = 1 + (spec.eye_scale[1] - 1) * intensity
        w, h = round(BASE_EYE["width"] * sx), round(BASE_EYE["height"] * sy)
        self.eyes.eyes_width(w, w)
        self.eyes.eyes_height(h, h)
        self.eyes.mood = spec.mood
        self.eyes.set_idle_mode(ON if spec.idle and look is None else OFF, 2, 2)
        self.eyes.set_auto_blinker(ON, *spec.blink)
        self.eyes.position = LOOKS[look] if look else spec.position
        if spec.anim == "laugh":
            self.eyes.laugh()
        elif spec.anim == "confuse":
            self.eyes.confuse()

    def handle_events(self, events: list[InputEvent]) -> None:
        for event in events:
            if event.kind == "quit":
                self.callbacks.on_quit()
            elif self._is_stop(event):
                self.callbacks.on_stop()

    def _is_stop(self, event: InputEvent) -> bool:
        if event.kind == "key":
            return event.key == "escape"
        return (event.kind == "pointer_down" and self.state.show_stop
                and STOP_BUTTON.collidepoint(event.pos))

    def _on_show(self, _eyes: RoboEyes) -> None:
        mouth = EXPRESSIONS[self.state.expression].mouth
        self._small.fill(BACKGROUND, MOUTH_AREA)
        draw_mouth(self._small, MOUTH_AREA, mouth, open_amount=self.level(),
                   intensity=self.state.intensity, colour=ACCENT)
        screen = self.display.surface
        pygame.transform.scale(self._small, LOGICAL_SCREEN, screen)
        if self.state.show_stop:
            self._draw_stop_button(screen)
        if self.state.status == "offline":
            _draw_no_wifi(screen, (1200, 70))
        self.display.present()

    def _draw_stop_button(self, screen: pygame.Surface) -> None:
        pygame.draw.rect(screen, (200, 60, 60), STOP_BUTTON, border_radius=18)
        if self._font is None and pygame.font.get_init():
            self._font = pygame.font.Font(None, 48)
        if self._font is not None:
            label = self._font.render("Stop", True, (255, 255, 255))
            screen.blit(label, label.get_rect(center=STOP_BUTTON.center))

    def tick(self) -> None:
        self.handle_events(self.display.poll_events())
        self.eyes.update()

    async def run(self) -> None:
        self._running = True
        while self._running:
            self.tick()
            await asyncio.sleep(1 / self.fps)

    def stop(self) -> None:
        self._running = False


def _draw_no_wifi(screen: pygame.Surface, centre: tuple[int, int]) -> None:
    x, y = centre
    colour = (230, 150, 60)
    for radius in (14, 28, 42):
        pygame.draw.arc(screen, colour, (x - radius, y - radius + 20, 2 * radius, 2 * radius),
                        0.8, 2.35, 5)
    pygame.draw.circle(screen, colour, (x, y + 20), 5)
    pygame.draw.line(screen, colour, (x - 40, y - 25), (x + 40, y + 35), 6)
