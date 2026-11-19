# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""People and camera tools through the agent loop, with a fake Claude and synthetic faces."""

from __future__ import annotations

from typing import Any

import pytest

from cadbot.bus import Observation
from cadbot.platform.base import Frame
from tests.fakes.claude import reply, tool_use
from tests.fakes.harness import AgentHarness, make_harness, utterance
from tests.fakes.vision import face, frame


def last_results(h: AgentHarness) -> list[dict[str, Any]]:
    return [b for b in h.client.requests[-1]["messages"][-1]["content"]
            if b.get("type") == "tool_result"]


async def with_face(h: AgentHarness, seed: int = 1, image: Frame | None = None) -> int:
    """Put a face in front of the fake camera; returns its track number."""
    assert h.reader is not None and h.analyzer is not None and h.vision is not None
    h.analyzer.faces = [face(seed)]
    h.reader.push(image or frame())
    await h.vision.step()
    return h.vision.tracker.visible()[0].track_id


@pytest.fixture
def h() -> AgentHarness:
    return make_harness(with_vision=True)


async def test_meet_and_remember_someone(h: AgentHarness) -> None:
    track = await with_face(h)
    h.client.script = [reply(tool_use("remember_person", track=track, name="Sam",
                                      description="red jacket")), reply()]
    await h.agent.handle(utterance("I'm Sam"))
    assert "held in memory only" in last_results(h)[0]["content"]
    assert h.people is not None
    (person,) = h.people.find("Sam")
    assert h.people.store.load_all() == []  # nothing saved before a yes

    h.client.script = [reply(tool_use("confirm_remember", person_id=person.person_id,
                                      accepted=True)), reply()]
    await h.agent.handle(utterance("Yes, please remember me"))
    assert "Saved Sam" in last_results(h)[0]["content"]
    (saved,) = h.people.store.load_all()
    assert saved.consent.reference == "Yes, please remember me"


async def test_readings_reach_claude_with_the_frame(h: AgentHarness) -> None:
    await with_face(h)
    assert h.vision is not None
    h.client.script = [reply()]
    await h.agent.handle(Observation(h.vision.snapshot(), "a new face appeared"))  # type: ignore[arg-type]
    content = h.client.requests[0]["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert "track 1: unknown (frontal)" in content[1]["text"]


async def test_saying_no_saves_nothing(h: AgentHarness) -> None:
    track = await with_face(h)
    assert h.people is not None
    h.client.script = [reply(tool_use("remember_person", track=track, name="Raj")), reply()]
    await h.agent.handle(utterance("I'm Raj"))
    (person,) = h.people.find("Raj")
    h.client.script = [reply(tool_use("confirm_remember", person_id=person.person_id,
                                      accepted=False)), reply()]
    await h.agent.handle(utterance("No thanks"))
    assert h.people.store.load_all() == []
    assert "Not saved" in last_results(h)[0]["content"]


async def _saved_person(h: AgentHarness, name: str = "Priya") -> str:
    track = await with_face(h)
    assert h.people is not None and h.vision is not None
    person = h.people.remember_pending(h.vision.tracker.get(track), name=name,  # type: ignore[arg-type]
                                       description="", declined=False, lighting="day",
                                       thumbnail_jpeg=None)
    h.people.confirm(person.person_id, True, permanent=False, consent_reference="yes")
    return person.person_id


async def test_forget_me_needs_a_separate_yes(h: AgentHarness) -> None:
    person_id = await _saved_person(h)
    assert h.people is not None
    h.client.script = [reply(tool_use("forget_person", person_id=person_id)), reply()]
    await h.agent.handle(utterance("Forget me"))
    result = last_results(h)[0]["content"]
    assert "Needs confirmation" in result
    token = result.split("confirm_token=")[1].rstrip(".")

    # Claude tries to confirm without a new utterance (on a camera frame): refused.
    assert h.vision is not None
    h.client.script = [reply(tool_use("forget_person", person_id=person_id,
                                      confirm_token=token)), reply()]
    await h.agent.handle(Observation(h.vision.snapshot(), "heartbeat"))  # type: ignore[arg-type]
    assert "separate spoken answer" in last_results(h)[0]["content"]
    assert len(h.people.store.load_all()) == 1

    h.client.script = [reply(tool_use("forget_person", person_id=person_id,
                                      confirm_token=token)), reply()]
    await h.agent.handle(utterance("Yes, forget me"))
    assert "Done: erased Priya" in last_results(h)[0]["content"]
    assert h.people.store.load_all() == []


async def test_cannot_forget_someone_who_is_not_here(h: AgentHarness) -> None:
    person_id = await _saved_person(h, "Raj")
    assert h.vision is not None and h.people is not None
    h.vision.tracker.tracks.clear()  # Raj has left; someone else asks
    h.client.script = [reply(tool_use("forget_person", person_id=person_id)), reply()]
    await h.agent.handle(utterance("Forget Raj"))
    result = last_results(h)[0]
    assert result["is_error"] and "only the person themselves" in result["content"]
    assert "cadbot.admin" in result["content"]
    assert len(h.people.store.load_all()) == 1


async def test_watch_interval_and_gaze_tools(h: AgentHarness) -> None:
    track = await with_face(h)
    h.client.script = [reply(tool_use("set_watch_interval", seconds=15),
                             tool_use("set_gaze", target=f"track {track}"),
                             tool_use("set_gaze", target="track 99")), reply()]
    await h.agent.handle(utterance("keep an eye out"))
    watch, _gaze_ok, gaze_bad = last_results(h)
    assert "every 15 seconds" in watch["content"]
    assert h.vision is not None and h.vision.gaze_mode == f"track {track}"
    assert gaze_bad["is_error"]


async def test_tools_degrade_without_a_camera() -> None:
    h = make_harness()  # no vision
    h.client.script = [reply(tool_use("remember_person", track=1, name="Sam")), reply()]
    await h.agent.handle(utterance("I'm Sam"))
    result = last_results(h)[0]
    assert result["is_error"] and "isn't available" in result["content"]


async def test_observations_are_dropped_while_offline(h: AgentHarness) -> None:
    await with_face(h)
    assert h.vision is not None
    h.health.mark_offline()
    await h.agent.handle(Observation(h.vision.snapshot(), "heartbeat"))  # type: ignore[arg-type]
    assert h.client.requests == [] and h.spoken_texts == []


async def test_failed_observations_stay_silent(h: AgentHarness) -> None:
    from cadbot.agent.errors import ClaudeFailure, ErrorKind

    await with_face(h)
    assert h.vision is not None
    h.client.script = [ClaudeFailure(ErrorKind.AUTH, "bad key")]
    await h.agent.handle(Observation(h.vision.snapshot(), "heartbeat"))  # type: ignore[arg-type]
    assert h.spoken_texts == [] and len(h.notifier.alerts) == 1
