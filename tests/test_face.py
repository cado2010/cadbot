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

    def settle() -> tuple[float, float]:
        for _ in range(25):
            face.tick()
        return face._pupil

    face.set("neutral")
    face.set_gaze_point((0.4, 0.0))
    assert settle()[0] == pytest.approx(0.4 * face.gaze_gain, abs=0.02)  # amplified
    face.set("thinking")  # someone in view: they win over thinking's up-left glance
    assert settle()[0] > 0.6
    face.set_gaze_point(None)  # nobody in view: the expression's own direction
    x, y = settle()
    assert x < -0.5 and y < -0.5
    face.set_gaze_point((0.5, 0.0))
    face.set("neutral", look="down")  # a direction Claude chose wins over everything
    x, y = settle()
    assert y > 0.8 and abs(x) < 0.1


def test_gaze_follows_a_person_across_the_frame(display: PygameDisplay) -> None:
    face = Face(display)
    face.set("neutral")
    positions = []
    for camera_x in (-0.6, -0.2, 0.2, 0.6):  # walking across in front of the device
        face.set_gaze_point((camera_x, 0.0))
        for _ in range(25):
            face.tick()
        positions.append(face._pupil[0])
    assert positions == sorted(positions)  # pupils move steadily the same way
    assert positions[-1] - positions[0] > 1.5  # clearly visible, not a twitch
    face.gaze_flip = True
    face.set_gaze_point((0.61, 0.0))
    for _ in range(25):
        face.tick()
    assert face._pupil[0] < -0.9  # flipped for cameras that mirror their image


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


def test_portrait_layout_fits_and_nothing_overlaps(display: PygameDisplay) -> None:
    from cadbot.face.renderer import EYE_AREA, PREVIEW_RECT, STOP_BUTTON
    from cadbot.platform.base import LOGICAL_SCREEN

    screen = pygame.Rect((0, 0), LOGICAL_SCREEN)
    assert LOGICAL_SCREEN == (720, 1280)  # portrait, like the Pi's Touch Display 2
    face = Face(display)
    mouth = pygame.Rect(0, 0, 300, 120)
    mouth.center = face._mouth_centre()
    for rect in (EYE_AREA, PREVIEW_RECT, STOP_BUTTON, mouth):
        assert screen.contains(rect), rect
    face_box = EYE_AREA.union(mouth)
    assert not face_box.colliderect(PREVIEW_RECT) and not face_box.colliderect(STOP_BUTTON)
    assert not PREVIEW_RECT.colliderect(STOP_BUTTON)
    assert abs(EYE_AREA.centerx - screen.centerx) <= 1  # face centred across


def test_small_window_shows_the_whole_portrait_screen() -> None:
    from cadbot.platform.base import InputEvent

    display = PygameDisplay(fullscreen=False, video_driver="dummy", window_size=(450, 800))
    display.open()
    try:
        display.surface.fill((200, 0, 0))
        display.present()
        window = pygame.display.get_surface()
        assert window.get_size() == (450, 800)
        for corner in ((3, 3), (446, 796)):  # scaled to fill the window: no letterbox bars
            r, g, b = window.get_at(corner)[:3]
            assert r > 190 and g < 10 and b < 10
        # a click in the small window maps back to full-size screen coordinates
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(225, 400), button=1))
        events = [e for e in display.poll_events() if e.kind == "pointer_down"]
        assert events == [InputEvent("pointer_down", pos=(360, 640))]
    finally:
        display.close()


def test_smiling_eyes_keep_the_pupil_visible(display: PygameDisplay) -> None:
    from cadbot.face.renderer import HAPPY_LID_RATIO, PUPIL, SMILE_MAX_PUPIL_Y

    face = Face(display)
    assert face.eyes.happyLidRatio == HAPPY_LID_RATIO < 0.5  # shallower than RoboEyes' half
    assert face.eyes.happyLidFlatness > 0  # gentle curve, not the eye's tight corners
    face.set_gaze_point((0.3, 1.0))  # the person is below the camera
    for name in ("happy", "laughing"):
        face.set(name)
        face.eyes.set_auto_blinker(0)
        for _ in range(40):
            face.eyes.fpsTimer = -10_000
            face.tick()
        assert face._pupil[1] <= SMILE_MAX_PUPIL_Y + 0.01  # pupils stay above the lid
        assert bytes(PUPIL) in pygame.image.tobytes(display.surface, "RGB"), name
    face.set("neutral")  # not smiling: looking down is allowed again
    for _ in range(40):
        face.tick()
    assert face._pupil[1] > 0.9
