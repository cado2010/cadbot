# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Draws the face in the Display. Animation only: Claude chooses every expression.

RoboEyes animates in a small logical space (320 x 135 units) and the framebuffer adapter
draws its shapes 4x larger, straight onto the top of the 1280x720 screen, with smooth
edges. cadbot draws the mouth below, then the stop button and status icons.
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
from cadbot.platform.base import Display, InputEvent
from cadbot.vendor.roboeyes import DEFAULT, OFF, ON, RoboEyes

log = logging.getLogger(__name__)

SCALE = 4  # logical RoboEyes units -> screen pixels
EYE_LOGICAL = (288, 120)
# Where the eyes may move, with a margin so they never touch the screen edge.
EYE_AREA = pygame.Rect(64, 60, EYE_LOGICAL[0] * SCALE, EYE_LOGICAL[1] * SCALE)
BASE_EYE = {"width": 68, "height": 76, "radius": 20, "spacing": 36}
MOUTH_GAP = 18  # logical units between the bottom of the eyes and the mouth
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
        self._font: pygame.font.Font | None = None
        self._mouth_pos: tuple[float, float] | None = None
        self._gaze: tuple[float, float] | None = None
        self._running = False
        self._version = 0
        self.fb = PygameFrameBuffer(display.surface.subsurface(EYE_AREA), BACKGROUND, ACCENT,
                                    scale=SCALE)
        # RoboEyes draws once inside its constructor, so all state above must exist first.
        self.eyes = RoboEyes(self.fb, *EYE_LOGICAL, frame_rate=fps, on_show=self._on_show)
        self.eyes.eyes_radius(BASE_EYE["radius"], BASE_EYE["radius"])
        self.eyes.eyes_spacing(BASE_EYE["spacing"])
        self.eyes.open()
        self.set("neutral")

    # ----------------------------------------------------------------- what Claude controls

    def set(self, expression: str, intensity: float = 1.0, look: str | None = None) -> None:
        if expression not in EXPRESSIONS:
            raise ValueError(f"unknown expression {expression!r}")
        if look is not None and look not in LOOKS:
            raise ValueError(f"unknown look {look!r}")
        self._version += 1
        self._gaze = None  # the next gaze update re-aims the eyes
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

    def set_gaze_point(self, point: tuple[float, float] | None) -> None:
        """Point the eyes at a person (x, y in -1..1), or let go with None.

        Following only applies to expressions that look straight ahead and when Claude
        hasn't chosen a direction with set_face(look=...); a small dead zone stops jitter.
        """
        spec = EXPRESSIONS[self.state.expression]
        if point is None or self.state.look is not None or spec.position != DEFAULT:
            if self._gaze is not None:
                self._gaze = None
                self._apply(spec, self.state.intensity, self.state.look)
            return
        last = self._gaze
        if last is not None and abs(point[0] - last[0]) < 0.08 \
                and abs(point[1] - last[1]) < 0.08:
            return
        self._gaze = point
        self.eyes.set_idle_mode(OFF)
        self.eyes.look_at(point[0], point[1] * 0.6)

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
        # RoboEyes works out positions from the *current* (still animating) width, which
        # pushed the eyes off-centre; settle the width first so positions are right.
        self.eyes.eyeLwidthCurrent = self.eyes.eyeRwidthCurrent = w
        self.eyes.spaceBetweenCurrent = self.eyes.spaceBetweenNext
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

    def _on_show(self, eyes: RoboEyes) -> None:
        mouth = EXPRESSIONS[self.state.expression].mouth
        screen = self.display.surface
        _clear_outside(screen, EYE_AREA)
        draw_mouth(screen, self._mouth_centre(eyes), mouth, open_amount=self.level(),
                   intensity=self.state.intensity, scale=SCALE, colour=ACCENT)
        if self.state.show_stop:
            self._draw_stop_button(screen)
        if self.state.status == "offline":
            _draw_no_wifi(screen, (1200, 70))
        self.display.present()

    def _mouth_centre(self, e: RoboEyes) -> tuple[int, int]:
        """Under the eyes, following them as they look around, eased like the eyes."""
        x = e.eyeLxNext + (e.eyeLwidthNext + e.spaceBetweenNext + e.eyeRwidthNext) / 2
        y = e.eyeLyNext + e.eyeLheightDefault + MOUTH_GAP
        target = (EYE_AREA.x + x * SCALE, EYE_AREA.y + y * SCALE)
        if self._mouth_pos is None:
            self._mouth_pos = target
        px, py = self._mouth_pos
        self._mouth_pos = (px + (target[0] - px) * 0.5, py + (target[1] - py) * 0.5)
        return round(self._mouth_pos[0]), round(self._mouth_pos[1])

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


def _clear_outside(screen: pygame.Surface, inner: pygame.Rect) -> None:
    """Clear the screen around the eye area (RoboEyes clears the area itself)."""
    w, h = screen.get_size()
    for rect in ((0, 0, w, inner.top), (0, inner.bottom, w, h - inner.bottom),
                 (0, inner.top, inner.left, inner.h), (inner.right, inner.top,
                                                       w - inner.right, inner.h)):
        screen.fill(BACKGROUND, rect)


def _draw_no_wifi(screen: pygame.Surface, centre: tuple[int, int]) -> None:
    x, y = centre
    colour = (230, 150, 60)
    for radius in (14, 28, 42):
        pygame.draw.arc(screen, colour, (x - radius, y - radius + 20, 2 * radius, 2 * radius),
                        0.8, 2.35, 5)
    pygame.draw.circle(screen, colour, (x, y + 20), 5)
    pygame.draw.line(screen, colour, (x - 40, y - 25), (x + 40, y + 35), 6)
