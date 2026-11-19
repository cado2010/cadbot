# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""The face: every expression from the design renders; input handling; presets."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pygame
import pytest

from cadbot.face.expressions import EXPRESSIONS, PRESET_MOMENTS
from cadbot.face.renderer import STOP_BUTTON, Face, FaceCallbacks
from cadbot.platform.base import InputEvent
from cadbot.platform.common.pygame_display import PygameDisplay
from cadbot.vendor.roboeyes import S

DESIGN_EXPRESSIONS = {"neutral", "listening", "thinking", "curious", "happy", "laughing", "sad",
                      "confused", "surprised", "concerned", "sleepy", "empathetic", "calm"}


@pytest.fixture
def display() -> Iterator[PygameDisplay]:
    d = PygameDisplay(fullscreen=False, video_driver="dummy")
    d.open()
    yield d
    d.close()


def test_expression_table_matches_design() -> None:
    assert set(EXPRESSIONS) == DESIGN_EXPRESSIONS


@pytest.mark.parametrize("name", sorted(DESIGN_EXPRESSIONS))
def test_each_expression_renders(display: PygameDisplay, name: str) -> None:
    face = Face(display)
    face.set(name, intensity=0.7, look="left")
    for _ in range(5):
        face.eyes.fpsTimer = -10_000  # force a frame
        face.tick()
    assert display.surface.get_at((640, 360)) is not None
    assert face.state.expression == name


def test_mouth_moves_with_audio_level(display: PygameDisplay) -> None:
    level = [0.0]
    face = Face(display, level=lambda: level[0])
    face.set("neutral")
    face.eyes.fpsTimer = -10_000
    face.tick()
    closed = display.surface.copy()
    level[0] = 1.0
    face.eyes.fpsTimer = -10_000
    face.tick()
    mouth = pygame.Rect(480, 560, 320, 160)  # the mouth strip, scaled to 1280x720

    def pixels(surface: pygame.Surface) -> bytes:
        return pygame.image.tobytes(surface.subsurface(mouth).copy(), "RGB")

    assert pixels(closed) != pixels(display.surface)


def test_invalid_names_are_rejected(display: PygameDisplay) -> None:
    face = Face(display)
    with pytest.raises(ValueError):
        face.set("furious")
    with pytest.raises(ValueError):
        face.set("happy", look="sideways")
    with pytest.raises(ValueError):
        face.set_presets({"bedtime": "sleepy"})


def test_escape_and_stop_button(display: PygameDisplay) -> None:
    stops: list[int] = []
    quits: list[int] = []
    face = Face(display, callbacks=FaceCallbacks(on_stop=lambda: stops.append(1),
                                                 on_quit=lambda: quits.append(1)))
    face.handle_events([InputEvent("key", key="escape")])
    face.handle_events([InputEvent("pointer_down", pos=STOP_BUTTON.center)])
    assert stops == [1]  # the button only works while it is shown
    face.set_busy(True)
    face.handle_events([InputEvent("pointer_down", pos=STOP_BUTTON.center),
                        InputEvent("pointer_down", pos=(10, 10)), InputEvent("quit")])
    assert stops == [1, 1] and quits == [1]


def test_injected_events_reach_the_face(display: PygameDisplay) -> None:
    stops: list[int] = []
    face = Face(display, callbacks=FaceCallbacks(on_stop=lambda: stops.append(1)))
    display.inject(InputEvent("key", key="escape"))
    face.tick()
    assert stops == [1]


def test_presets(display: PygameDisplay) -> None:
    face = Face(display)
    assert set(face.state.presets) == set(PRESET_MOMENTS)
    face.set_presets({"idle": "sleepy"})
    face.apply_preset("idle")
    assert face.state.expression == "sleepy"
    face.apply_preset("speaking")  # None: leave the face as it is
    assert face.state.expression == "sleepy"


async def test_scheduled_preset_yields_to_newer_expression(display: PygameDisplay) -> None:
    face = Face(display)
    face.set("happy")
    face.schedule_preset("idle", 0.01)
    face.set("sad")
    await asyncio.sleep(0.05)
    assert face.state.expression == "sad"
    face.schedule_preset("idle", 0.01)
    await asyncio.sleep(0.05)
    assert face.state.expression == "neutral"


def test_vendored_roboeyes_fix_keeps_eyes_on_screen(display: PygameDisplay) -> None:
    face = Face(display)
    face.eyes.position = S
    assert face.eyes.eyeLyNext <= face.eyes.get_screen_constraint_Y()
    face.eyes.look_at(1.0, -1.0)
    assert face.eyes.eyeLxNext == face.eyes.get_screen_constraint_X()
    assert face.eyes.eyeLyNext == 0
