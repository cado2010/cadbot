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
    mouth = pygame.Rect(0, 0, 320, 120)
    mouth.center = face._mouth_centre(face.eyes)

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


def test_the_face_never_moves_only_the_pupils(display: PygameDisplay) -> None:
    face = Face(display)
    def pair_centre() -> tuple[float, float]:
        e = face.eyes
        return (e.eyeLxNext + (e.eyeLwidthNext + e.spaceBetweenNext + e.eyeRwidthNext) / 2,
                e.eyeLyNext + e.eyeLheightDefault / 2)

    centre = pair_centre()
    for name in ("neutral", "thinking", "curious", "sad", "surprised", "happy"):
        face.set(name, look="left" if name == "happy" else None)
        face.set_gaze_point((1.0, 0.5))
        for _ in range(10):
            face.tick()
        x, y = pair_centre()
        assert abs(x - centre[0]) <= 1 and abs(y - centre[1]) <= 1, name  # eyes stay put
        assert not face.eyes.idle
        assert face._mouth_centre() == face._mouth_centre(face.eyes)  # mouth fixed
    face.set("neutral")
    for _ in range(20):
        face.tick()
    assert face._pupil[0] > 0.8  # following a person moves the pupils right
    face.set("thinking")
    for _ in range(20):
        face.tick()
    assert face._pupil[0] < -0.5 and face._pupil[1] < -0.5  # thinking looks up-left
    face.set("neutral", look="down")
    for _ in range(20):
        face.tick()
    assert face._pupil[1] > 0.8 and abs(face._pupil[0]) < 0.1  # Claude's look wins


def test_pupils_are_drawn_inside_the_eyes(display: PygameDisplay) -> None:
    from cadbot.face.renderer import IRIS, PUPIL

    face = Face(display)
    face.set("neutral")
    face.eyes.set_auto_blinker(0)
    for _ in range(30):
        face.eyes.fpsTimer = -10_000
        face.tick()
    pixels = pygame.image.tobytes(display.surface, "RGB")
    assert bytes(IRIS) in pixels and bytes(PUPIL) in pixels


def test_camera_preview_in_the_lower_left(display: PygameDisplay) -> None:
    import numpy as np

    from cadbot.face.renderer import BOX_COLOURS, PREVIEW_RECT
    from cadbot.vision.loop import Preview, PreviewBox

    face = Face(display)
    rgb = np.zeros((144, 256, 3), dtype=np.uint8)
    rgb[:, :, 2] = 200  # blue picture
    face.preview = lambda: Preview(rgb, (PreviewBox(0.5, 0.25, 0.25, 0.5, "known"),), False)
    face.eyes.fpsTimer = -10_000
    face.tick()
    assert display.surface.get_at(PREVIEW_RECT.move(10, 10).topleft)[:3] == (0, 0, 200)
    edge = (PREVIEW_RECT.x + 128, PREVIEW_RECT.y + 36 + 20)
    assert display.surface.get_at(edge)[:3] == BOX_COLOURS["known"]

    face.preview = None  # switched off in config: nothing drawn there
    face.eyes.fpsTimer = -10_000
    face.tick()
    assert display.surface.get_at(PREVIEW_RECT.move(10, 10).topleft)[:3] != (0, 0, 200)


def test_preview_failure_never_breaks_the_face(display: PygameDisplay) -> None:
    face = Face(display)

    def broken() -> None:
        raise RuntimeError("camera unplugged")

    face.preview = broken  # type: ignore[assignment]
    face.eyes.fpsTimer = -10_000
    face.tick()  # no exception
