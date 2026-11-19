# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Draws the face in the Display. Animation only: Claude chooses every expression.

The face never moves around the screen: the eyes and mouth stay put, and only the
expression changes (eyelids, eye shape, blinks, mouth). RoboEyes animates the eye shapes in a
small logical space, drawn 4x larger with smooth edges. cadbot adds an iris and pupil inside
each eye, clipped to the eye's current shape so eyelids and blinks cover them, and moves only
the pupils: to look at someone, up while thinking, or down when sad.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pygame

from cadbot.face.expressions import DEFAULT_PRESETS, EXPRESSIONS, LOOKS, Expression
from cadbot.face.fb_pygame import PygameFrameBuffer
from cadbot.face.mouth import draw_mouth
from cadbot.platform.base import Display, InputEvent
from cadbot.vendor.roboeyes import DEFAULT, NE, NW, OFF, ON, SE, SW, E, N, RoboEyes, S, W

if TYPE_CHECKING:
    from cadbot.vision.loop import Preview

log = logging.getLogger(__name__)

SCALE = 4  # logical RoboEyes units -> screen pixels
EYE_LOGICAL = (288, 120)
EYE_AREA = pygame.Rect(64, 60, EYE_LOGICAL[0] * SCALE, EYE_LOGICAL[1] * SCALE)
BASE_EYE = {"width": 38, "height": 41, "radius": 18, "spacing": 40}
MOUTH_GAP = 20  # logical units between the bottom of the eyes and the mouth
MOUTH_CENTRE = (EYE_AREA.centerx,
                EYE_AREA.y + round((EYE_LOGICAL[1] / 2 + BASE_EYE["height"] / 2 + MOUTH_GAP)
                                   * SCALE))
STOP_BUTTON = pygame.Rect(1090, 600, 160, 80)
PREVIEW_RECT = pygame.Rect(24, 552, 256, 144)  # lower-left corner
BOX_COLOURS = {"known": (90, 210, 120), "unsure": (240, 180, 60), "unknown": (235, 235, 235)}

BACKGROUND = (8, 10, 18)
SCLERA = (236, 240, 246)
IRIS = (64, 132, 186)
IRIS_RIM = (34, 80, 124)
PUPIL = (10, 12, 20)
MOUTH_COLOUR = (226, 232, 240)
PUPIL_RANGE = (0.32, 0.26)
"""How far the iris moves from the centre, as a share of the eye's width and height."""

DIRECTIONS: dict[int, tuple[float, float]] = {
    DEFAULT: (0.0, 0.0), N: (0.0, -1.0), NE: (0.7, -0.7), E: (1.0, 0.0), SE: (0.7, 0.7),
    S: (0.0, 1.0), SW: (-0.7, 0.7), W: (-1.0, 0.0), NW: (-0.7, -0.7),
}


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
        self._gaze: tuple[float, float] | None = None
        self._pupil = (0.0, 0.0)
        self._glance = (0.0, 0.0)
        self._next_glance = 0.0
        self._confused_until = 0.0
        self.gaze_gain = 1.8
        """How strongly the pupils follow a person (the camera's view is wide)."""
        self.gaze_flip = False
        """Set if the eyes follow the wrong way (some cameras deliver mirrored images)."""
        self.preview: Callable[[], Preview | None] | None = None
        """Camera preview source (lower-left corner); None hides it."""
        self._preview_surface: tuple[int, pygame.Surface] | None = None
        self._running = False
        self._version = 0
        self.fb = PygameFrameBuffer(display.surface.subsurface(EYE_AREA), BACKGROUND, SCLERA,
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
        spec = EXPRESSIONS[expression]
        intensity = max(0.0, min(1.0, intensity))
        self.state.expression, self.state.intensity, self.state.look = expression, intensity, look
        self._apply(spec, intensity)

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
        """Look at a person (x, y in -1..1 in the camera image, already mirrored), or let go
        with None. Only the pupils move. A person in view wins over the expression's own
        direction; only a direction Claude chose with set_face(look=...) wins over them. A
        small dead zone stops jitter.
        """
        if point is None:
            self._gaze = None
            return
        last = self._gaze
        if last is not None and abs(point[0] - last[0]) < 0.08 \
                and abs(point[1] - last[1]) < 0.08:
            return
        self._gaze = point

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

    def _apply(self, spec: Expression, intensity: float) -> None:
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
        self.eyes.set_idle_mode(OFF)  # the eyes never wander; only the pupils glance
        self.eyes.set_auto_blinker(ON, *spec.blink)
        self.eyes.position = DEFAULT  # always centred: the face stays still
        if spec.anim == "confuse":
            self._confused_until = time.monotonic() + 0.6

    def _pupil_target(self, now: float) -> tuple[float, float]:
        spec = EXPRESSIONS[self.state.expression]
        if self.state.look is not None:  # Claude chose a direction on purpose
            x, y = DIRECTIONS[LOOKS[self.state.look]]
        elif self._gaze is not None:  # someone is in view: look at them
            gx, gy = self._gaze
            x = gx * self.gaze_gain * (-1 if self.gaze_flip else 1)
            y = gy * self.gaze_gain
        elif spec.position != DEFAULT:  # the expression's own direction (thinking: up-left)
            x, y = DIRECTIONS[spec.position]
        elif spec.idle:
            if now >= self._next_glance:  # an occasional small glance, like a real face
                glance = random.random() < 0.6
                self._glance = (random.uniform(-0.5, 0.5), random.uniform(-0.3, 0.3)) \
                    if glance else (0.0, 0.0)
                self._next_glance = now + random.uniform(2.0, 5.0)
            x, y = self._glance
        else:
            x, y = 0.0, 0.0
        if now < self._confused_until:  # a quick puzzled look from side to side
            x += 0.6 * math.sin(now * 28)
        return max(-1.0, min(1.0, x)), max(-1.0, min(1.0, y))

    def _update_pupils(self) -> None:
        tx, ty = self._pupil_target(time.monotonic())
        px, py = self._pupil
        self._pupil = (px + (tx - px) * 0.35, py + (ty - py) * 0.35)

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
        self._draw_irises(eyes)
        mouth = EXPRESSIONS[self.state.expression].mouth
        screen = self.display.surface
        _clear_outside(screen, EYE_AREA)
        draw_mouth(screen, self._mouth_centre(eyes), mouth, open_amount=self.level(),
                   intensity=self.state.intensity, scale=SCALE, colour=MOUTH_COLOUR)
        if self.preview is not None:
            self._draw_preview(screen)
        if self.state.show_stop:
            self._draw_stop_button(screen)
        if self.state.status == "offline":
            _draw_no_wifi(screen, (1200, 70))
        self.display.present()

    def _mouth_centre(self, _eyes: RoboEyes | None = None) -> tuple[int, int]:
        """Fixed: the mouth never moves around the screen."""
        return MOUTH_CENTRE

    def _iris_centre(self, eye_cx: float, eye_cy: float) -> tuple[float, float]:
        """Iris centre in eye-area pixels: the eye's centre (logical units) plus the pupil
        offset."""
        return (eye_cx * SCALE + self._pupil[0] * PUPIL_RANGE[0] * BASE_EYE["width"] * SCALE,
                eye_cy * SCALE + self._pupil[1] * PUPIL_RANGE[1] * BASE_EYE["height"] * SCALE)

    def _draw_irises(self, e: RoboEyes) -> None:
        """Iris, pupil and highlight inside each eye, clipped to the visible white of the eye
        (so eyelids, happy cheeks and blinks cover them)."""
        area = self.fb.surface
        iris_r = round(BASE_EYE["width"] * SCALE * 0.30)
        for x, y, w, h in ((e.eyeLx, e.eyeLy, e.eyeLwidthCurrent, e.eyeLheightCurrent),
                           (e.eyeRx, e.eyeRy, e.eyeRwidthCurrent, e.eyeRheightCurrent)):
            if w <= 2 or h <= 2:
                continue
            rect = pygame.Rect(x * SCALE, y * SCALE, w * SCALE, h * SCALE).clip(area.get_rect())
            if rect.w <= 0 or rect.h <= 0:
                continue
            eye = area.subsurface(rect)
            white = pygame.mask.from_threshold(eye, (*SCLERA, 255), (40, 40, 40, 255))
            overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
            ix, iy = self._iris_centre(x + w / 2, y + h / 2)
            centre = (round(ix - rect.x), round(iy - rect.y))
            pygame.draw.aacircle(overlay, IRIS_RIM, centre, iris_r)
            pygame.draw.aacircle(overlay, IRIS, centre, round(iris_r * 0.84))
            pygame.draw.aacircle(overlay, PUPIL, centre, round(iris_r * 0.46))
            glint = (centre[0] - round(iris_r * 0.32), centre[1] - round(iris_r * 0.34))
            pygame.draw.aacircle(overlay, (255, 255, 255), glint, max(2, round(iris_r * 0.16)))
            clip = white.to_surface(setcolor=(255, 255, 255, 255), unsetcolor=(0, 0, 0, 0))
            overlay.blit(clip, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            eye.blit(overlay, (0, 0))

    def _draw_preview(self, screen: pygame.Surface) -> None:
        """What the camera sees, small and mirrored, so people can get themselves in frame.
        Face boxes: green = recognised, amber = not sure, white = not known."""
        assert self.preview is not None
        try:
            preview = self.preview()
        except Exception:  # a camera hiccup must never break the face
            log.debug("camera preview unavailable", exc_info=True)
            preview = None
        rect = PREVIEW_RECT
        if preview is None:
            pygame.draw.rect(screen, (40, 44, 56), rect, 2, border_radius=8)
            return
        key = id(preview.rgb)
        if self._preview_surface is None or self._preview_surface[0] != key:
            h, w = preview.rgb.shape[:2]
            image = pygame.image.frombuffer(preview.rgb.tobytes(), (w, h), "RGB")
            if (w, h) != rect.size:
                image = pygame.transform.smoothscale(image, rect.size)
            self._preview_surface = (key, image)
        screen.blit(self._preview_surface[1], rect)
        for box in preview.boxes:
            face = pygame.Rect(rect.x + round(box.x * rect.w), rect.y + round(box.y * rect.h),
                               max(4, round(box.w * rect.w)), max(4, round(box.h * rect.h)))
            pygame.draw.rect(screen, BOX_COLOURS.get(box.status, BOX_COLOURS["unknown"]),
                             face.clip(rect), 2, border_radius=4)
        pygame.draw.rect(screen, (70, 76, 92), rect.inflate(4, 4), 2, border_radius=8)

    def _draw_stop_button(self, screen: pygame.Surface) -> None:
        pygame.draw.rect(screen, (200, 60, 60), STOP_BUTTON, border_radius=18)
        if self._font is None and pygame.font.get_init():
            self._font = pygame.font.Font(None, 48)
        if self._font is not None:
            label = self._font.render("Stop", True, (255, 255, 255))
            screen.blit(label, label.get_rect(center=STOP_BUTTON.center))

    def tick(self) -> None:
        self.handle_events(self.display.poll_events())
        self._update_pupils()
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
