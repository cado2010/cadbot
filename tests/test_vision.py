# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Frame gate, tracker, angles, the event bus and the vision loop (synthetic faces only)."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from cadbot.bus import EventBus, Observation, Snapshot, Utterance
from cadbot.config import VisionConfig
from cadbot.people.registry import PeopleRegistry
from cadbot.people.store import PeopleStore
from cadbot.router import render_event
from cadbot.vision.faces import estimate_angle
from cadbot.vision.frame_gate import FrameGate, GateConfig
from cadbot.vision.image import grey_small, to_jpeg
from cadbot.vision.loop import VisionLoop
from cadbot.vision.tracker import Identity, Tracker
from tests.fakes.vision import FakeAnalyzer, FakeReader, face, frame


def grey(value: int) -> np.ndarray:
    return grey_small(frame(value).image)


# ----------------------------------------------------------------------- frame gate


def test_gate_first_frame_then_min_interval_then_change() -> None:
    gate = FrameGate(GateConfig(min_interval_s=10, watch_interval_s=300))
    assert gate.check(grey(60), 0) == "first frame"
    gate.mark_sent(grey(60), 0)
    assert gate.check(grey(200), 5) is None  # changed, but too soon
    assert gate.check(grey(60), 20) is None  # nothing changed
    assert gate.check(grey(200), 20) == "the scene changed"
    assert gate.check(grey(60), 20, new_face=True) == "a new face appeared"
    assert gate.check(grey(60), 301) == "heartbeat"


def test_watch_interval_is_clamped() -> None:
    gate = FrameGate(GateConfig())
    assert gate.set_watch_interval(1) == 10
    assert gate.set_watch_interval(99_999) == 3600
    assert gate.set_watch_interval(120) == 120


def test_small_noise_is_not_a_change() -> None:
    gate = FrameGate(GateConfig())
    a = grey(60)
    noisy = np.clip(a.astype(int) + np.random.default_rng(1).integers(-8, 8, a.shape),
                    0, 255).astype(np.uint8)
    gate.mark_sent(a, 0)
    assert gate.check(noisy, 50) is None


# ----------------------------------------------------------------------- tracker


def test_tracks_follow_faces_and_expire() -> None:
    tracker = Tracker(timeout_s=2)
    seen, new = tracker.update([face(1, x=100), face(2, x=800)], now=0)
    assert len(new) == 2
    ids = {t.track_id for t in seen}
    seen, new = tracker.update([face(1, x=130, noise=0.2), face(2, x=780, noise=0.2)], now=0.25)
    assert new == [] and {t.track_id for t in seen} == ids
    tracker.update([face(1, x=150)], now=1.0)
    tracker.update([face(1, x=160)], now=3.5)
    assert len(tracker.tracks) == 1  # face 2 left more than 2 s ago


def test_identity_sticks_until_someone_else_matches_repeatedly() -> None:
    tracker = Tracker()
    (track,), _ = tracker.update([face(1)], 0)
    track.update_identity(Identity("p_a", 0.8, "confident"))
    track.update_identity(None)  # turned away: identity holds
    assert track.identity is not None and track.identity.person_id == "p_a"
    for _ in range(2):
        track.update_identity(Identity("p_b", 0.7, "confident"))
    assert track.identity.person_id == "p_a"
    track.update_identity(Identity("p_b", 0.7, "confident"))
    assert track.identity.person_id == "p_b"


def test_angle_from_landmarks() -> None:
    def lm(nose_x: float) -> np.ndarray:
        return np.array([[100, 100], [160, 100], [nose_x, 130], [110, 160], [150, 160]],
                        dtype=np.float32)
    assert estimate_angle(lm(130)) == "frontal"
    assert estimate_angle(lm(145)) == "right"
    assert estimate_angle(lm(112)) == "left"
    assert estimate_angle(lm(175)) == "profile"


# ----------------------------------------------------------------------- bus and router


def snapshot(readings: str = "No faces in view.") -> Snapshot:
    return Snapshot(to_jpeg(frame().image), datetime(2026, 11, 19, 20, 0), True, readings)


async def test_bus_keeps_only_the_newest_observation() -> None:
    bus = EventBus()
    bus.put_nowait(Observation(snapshot("a"), "heartbeat"))
    bus.put_nowait(Utterance("hi", datetime.now(), 1.0))
    bus.put_nowait(Observation(snapshot("b"), "the scene changed"))
    first, second = await bus.get(), await bus.get()
    assert isinstance(first, Utterance)
    assert isinstance(second, Observation) and second.snapshot.readings == "b"
    assert bus.empty()


def test_router_sends_the_image_first() -> None:
    content = render_event(Observation(snapshot("track 1: unknown (frontal)"), "heartbeat"))
    assert content[0]["type"] == "image"
    assert base64.b64decode(content[0]["source"]["data"])[:2] == b"\xff\xd8"  # JPEG
    text = content[1]["text"]
    assert "[observation at" in text and "heartbeat" in text
    assert "Night vision" in text and "track 1: unknown" in text


def test_utterance_carries_the_latest_frame() -> None:
    content = render_event(Utterance("hello", datetime.now(), 1.0, snapshot=snapshot()))
    assert [b["type"] for b in content] == ["image", "text"]


# ----------------------------------------------------------------------- vision loop


@pytest.fixture
def people(tmp_path: Path) -> Iterator[PeopleRegistry]:
    store = PeopleStore(tmp_path / "cadbot.db", tmp_path / "faces")
    yield PeopleRegistry(store, VisionConfig())
    store.close()


def make_loop(people: PeopleRegistry) -> tuple[VisionLoop, FakeReader, FakeAnalyzer,
                                                 list[Observation], list[object]]:
    reader, analyzer, sent, gaze = FakeReader(), FakeAnalyzer(), [], []
    clock = [0.0]
    loop = VisionLoop(reader=reader, analyzer=analyzer,  # type: ignore[arg-type]
                      people=people, config=VisionConfig(), emit=sent.append,
                      clock=lambda: clock[0])
    loop.on_gaze = gaze.append
    loop.clock_ref = clock  # type: ignore[attr-defined]
    return loop, reader, analyzer, sent, gaze


async def test_vision_loop_sends_first_frame_and_new_faces(people: PeopleRegistry) -> None:
    loop, reader, analyzer, sent, gaze = make_loop(people)
    reader.push(frame())
    await loop.step()
    assert len(sent) == 1 and sent[0].reason == "first frame"
    assert sent[0].snapshot.readings == "No faces in view."

    loop.clock_ref[0] = 12.0  # type: ignore[attr-defined]
    analyzer.faces = [face(7, x=100)]
    reader.push(frame())
    await loop.step()
    assert sent[-1].reason == "a new face appeared"
    assert "track 1: unknown (frontal)" in sent[-1].snapshot.readings
    # the face is on the camera's left, so the eyes look to the screen's right
    assert gaze[-1] is not None and gaze[-1][0] > 0


async def test_vision_loop_recognises_saved_people(people: PeopleRegistry) -> None:
    loop, reader, analyzer, sent, _ = make_loop(people)
    analyzer.faces = [face(7)]
    reader.push(frame())
    await loop.step()
    track = loop.tracker.visible()[0]
    person = people.remember_pending(track, name="Sam", description="", declined=False,
                                     lighting="day", thumbnail_jpeg=None)
    people.confirm(person.person_id, True, permanent=False, consent_reference="yes please")
    loop.tracker.tracks.clear()  # Sam leaves and comes back
    loop.clock_ref[0] = 30.0  # type: ignore[attr-defined]
    analyzer.faces = [face(7, noise=0.3)]
    reader.push(frame(90))
    await loop.step()
    assert f"Sam ({person.person_id}" in sent[-1].snapshot.readings
    assert "confident" in sent[-1].snapshot.readings


async def test_same_frame_is_not_processed_twice(people: PeopleRegistry) -> None:
    loop, reader, analyzer, _, _ = make_loop(people)
    reader.push(frame())
    await loop.step()
    calls = analyzer.calls
    await loop.step()
    assert analyzer.calls == calls
