# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""The agent loop against a scripted fake Claude: tools, retries, errors, interruptions."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from cadbot.agent.errors import ClaudeFailure, ErrorKind
from cadbot.agent.loop import COMPACTION_BETA, FALLBACK_BETA
from cadbot.bus import BackOnline
from cadbot.config import AgentConfig
from tests.fakes.claude import Slow, reply, text, tool_use
from tests.fakes.harness import AgentHarness, make_harness, utterance


def tool_results(request: dict[str, Any]) -> list[dict[str, Any]]:
    last = request["messages"][-1]
    assert last["role"] == "user"
    return [b for b in last["content"] if b.get("type") == "tool_result"]


def assert_history_valid(messages: list[dict[str, Any]]) -> None:
    """Every tool_use must be answered by a tool_result in the next message."""
    for i, msg in enumerate(messages):
        if msg["role"] != "assistant":
            continue
        ids = {b["id"] for b in msg["content"] if b.get("type") == "tool_use"}
        if not ids:
            continue
        assert i + 1 < len(messages), "tool_use without a following user message"
        answered = {b["tool_use_id"] for b in messages[i + 1]["content"]
                    if b.get("type") == "tool_result"}
        assert ids <= answered


async def test_face_then_speech(harness: AgentHarness) -> None:
    harness.client.script = [
        reply(tool_use("set_face", expression="happy"), tool_use("speak", text="Hi there!")),
        reply(),
    ]
    await harness.agent.handle(utterance("hello cadbot"))
    assert harness.spoken_texts == ["Hi there!"]
    assert harness.face.state.expression == "happy"
    results = tool_results(harness.client.requests[1])
    assert [r["content"] for r in results] == ["ok", "Spoken."]
    assert_history_valid(harness.agent.session.messages)


async def test_first_request_carries_utterance_and_time(harness: AgentHarness) -> None:
    harness.client.script = [reply()]
    await harness.agent.handle(utterance("what time is it"))
    content = harness.client.requests[0]["messages"][0]["content"][0]["text"]
    assert '"what time is it"' in content
    assert "2:30 pm" in content


async def test_text_blocks_are_never_spoken(harness: AgentHarness) -> None:
    harness.client.script = [reply(text("I would say hello"))]
    await harness.agent.handle(utterance("hi"))
    assert harness.spoken_texts == []
    assert len(harness.audio.played) == 0


async def test_no_tool_call_means_do_nothing(harness: AgentHarness) -> None:
    harness.client.script = [reply()]
    await harness.agent.handle(utterance("(TV in the background)"))
    assert len(harness.client.requests) == 1
    assert harness.audio.played == []


async def test_long_speech_goes_back_to_claude(harness: AgentHarness) -> None:
    long_text = " ".join(["word"] * 70)
    harness.client.script = [
        reply(tool_use("speak", text=long_text)),
        reply(tool_use("speak", text="Short version.")),
        reply(),
    ]
    await harness.agent.handle(utterance("explain everything"))
    first = tool_results(harness.client.requests[1])[0]
    assert first["is_error"] is True
    assert "too long for speech" in first["content"]
    assert harness.spoken_texts == ["Short version."]


async def test_unknown_language_is_reported(harness: AgentHarness) -> None:
    harness.client.script = [reply(tool_use("speak", text="Hola", lang="es")), reply()]
    await harness.agent.handle(utterance("say hola"))
    result = tool_results(harness.client.requests[1])[0]
    assert result["is_error"] and "No voice" in result["content"]


async def test_invalid_tool_input_is_an_error_result(harness: AgentHarness) -> None:
    harness.client.script = [reply(tool_use("set_face", expression="furious")), reply()]
    await harness.agent.handle(utterance("hi"))
    result = tool_results(harness.client.requests[1])[0]
    assert result["is_error"] and "must be one of" in result["content"]


async def test_pause_turn_is_continued(harness: AgentHarness) -> None:
    harness.client.script = [reply(text("searching"), stop_reason="pause_turn"),
                             reply(tool_use("speak", text="Found it.")), reply()]
    await harness.agent.handle(utterance("search for something"))
    assert len(harness.client.requests) == 3
    assert harness.spoken_texts == ["Found it."]


async def test_refusal_is_not_added_to_history(harness: AgentHarness) -> None:
    harness.client.script = [reply(text("..."), stop_reason="refusal")]
    await harness.agent.handle(utterance("something"))
    assert [m["role"] for m in harness.agent.session.messages] == ["user"]


async def test_tool_round_cap() -> None:
    h = make_harness(config=AgentConfig(max_tool_rounds=3))
    h.client.script = [reply(tool_use("set_face", expression="neutral")) for _ in range(5)]
    await h.agent.handle(utterance("loop"))
    assert len(h.client.requests) == 3
    assert_history_valid(h.agent.session.messages)


async def test_request_params(harness: AgentHarness) -> None:
    harness.client.script = [reply()]
    await harness.agent.handle(utterance("hi"))
    params = harness.client.requests[0]
    assert params["model"] == "claude-opus-5-5"
    assert params["output_config"] == {"effort": "low"}
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert params["cache_control"] == {"type": "ephemeral"}
    assert params["betas"] == [COMPACTION_BETA, FALLBACK_BETA]
    assert params["fallbacks"] == "default"
    edit = params["context_management"]["edits"][0]
    assert edit["type"] == "compact_20260112" and edit["trigger"]["value"] >= 50_000
    names = [t["name"] for t in params["tools"]]
    assert names[:4] == ["set_face", "speak", "set_face_presets", "get_help"]
    assert {"set_watch_interval", "set_listening", "set_gaze", "remember_person",
            "confirm_remember", "update_person", "find_person", "forget_person"} <= set(names)
    assert names[-1] == "web_search"
    assert params["tools"][-1]["type"] == "web_search_20260209"
    assert "thinking" not in params and "temperature" not in params


async def test_fallbacks_can_be_turned_off() -> None:
    h = make_harness(config=AgentConfig(fallbacks="off"))
    h.client.script = [reply()]
    await h.agent.handle(utterance("hi"))
    assert "fallbacks" not in h.client.requests[0]
    assert h.client.requests[0]["betas"] == [COMPACTION_BETA]


async def test_system_prompt_is_identical_across_requests(harness: AgentHarness) -> None:
    harness.client.script = [reply(), reply()]
    await harness.agent.handle(utterance("one"))
    await harness.agent.handle(utterance("two"))
    first, second = harness.client.requests
    assert first["system"] == second["system"] and first["tools"] == second["tools"]


# ----------------------------------------------------------------------- errors


def overloaded() -> ClaudeFailure:
    return ClaudeFailure(ErrorKind.OVERLOADED, "overloaded_error", 529)


async def test_retries_then_succeeds(harness: AgentHarness) -> None:
    harness.client.script = [overloaded(), overloaded(),
                             reply(tool_use("speak", text="Here you go.")), reply()]
    await harness.agent.handle(utterance("hi"))
    assert harness.sleeps == [1.0, 4.0]
    # "One moment." is said once, when the wait passes about 3 seconds
    assert harness.spoken_texts.count("One moment.") == 1
    assert harness.spoken_texts[-1] == "Here you go."


async def test_gives_up_after_two_retries_and_explains(harness: AgentHarness) -> None:
    harness.client.script = [overloaded(), overloaded(), overloaded()]
    await harness.agent.handle(utterance("hi"))
    assert len(harness.client.requests) == 3
    assert any("very busy" in t for t in harness.spoken_texts)
    assert harness.face.state.expression == "confused"
    assert harness.notifier.alerts == []


@pytest.mark.parametrize(("kind", "phrase"), [
    (ErrorKind.AUTH, "API key needs checking"),
    (ErrorKind.BUDGET, "run out of my API budget"),
    (ErrorKind.PERMISSION, "isn't allowed to use that model"),
])
async def test_owner_errors_alert_and_explain(harness: AgentHarness, kind: ErrorKind,
                                              phrase: str) -> None:
    harness.client.script = [ClaudeFailure(kind, "detail")]
    await harness.agent.handle(utterance("hi"))
    assert len(harness.client.requests) == 1  # not retried
    assert any(phrase in t for t in harness.spoken_texts)
    assert len(harness.notifier.alerts) == 1


async def test_bad_request_is_explained_not_retried(harness: AgentHarness) -> None:
    harness.client.script = [ClaudeFailure(ErrorKind.BAD_REQUEST, "invalid_request_error")]
    await harness.agent.handle(utterance("hi"))
    assert len(harness.client.requests) == 1
    assert any("how I asked Claude" in t for t in harness.spoken_texts)


async def test_too_large_starts_fresh_and_retries_once(harness: AgentHarness) -> None:
    harness.client.script = [reply(), ClaudeFailure(ErrorKind.TOO_LARGE, "too long"), reply()]
    await harness.agent.handle(utterance("first"))
    await harness.agent.handle(utterance("second"))
    retry = harness.client.requests[-1]["messages"]
    assert len(retry) == 1 and "second" in retry[0]["content"][-1]["text"]


async def test_offline_plays_clip_and_queues_missed_utterances(harness: AgentHarness) -> None:
    harness.probe_result[0] = False
    harness.client.script = [ClaudeFailure(ErrorKind.OFFLINE, "connection error")]
    await harness.agent.handle(utterance("weather?"))
    assert not harness.health.online
    assert any("can't reach the internet" in t for t in harness.spoken_texts)
    calls = len(harness.client.requests)
    await harness.agent.handle(utterance("are you there?"))
    assert len(harness.client.requests) == calls  # no API call while offline
    missed = harness.agent.take_missed()
    assert [u.text for u in missed] == ["weather?", "are you there?"]


async def test_online_but_claude_unreachable_uses_second_clip(harness: AgentHarness) -> None:
    harness.probe_result[0] = True
    harness.client.script = [ClaudeFailure(ErrorKind.OFFLINE, "connection error")]
    await harness.agent.handle(utterance("hi"))
    assert any("I'm online, but I can't reach Claude" in t for t in harness.spoken_texts)


async def test_back_online_event_lists_missed(harness: AgentHarness) -> None:
    harness.client.script = [reply()]
    await harness.agent.handle(BackOnline(since=utterance("x").started_at,
                                          missed=(utterance("weather?"),)))
    content = harness.client.requests[0]["messages"][0]["content"][0]["text"]
    assert "[back_online" in content and '"weather?"' in content


# ----------------------------------------------------------------------- interruptions


async def _wait_until(predicate: Any, timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


async def test_interrupt_while_speaking_reports_what_was_heard() -> None:
    h = make_harness(audio_speed=1.0)  # play in real time so there is time to interrupt
    h.client.script = [
        reply(tool_use("speak", text="The first sentence is here. The second never gets said.")),
        reply(),
    ]
    task = asyncio.create_task(h.agent.handle(utterance("tell me something")))
    await _wait_until(lambda: len(h.audio.played) == 1 and h.audio.is_playing)
    h.agent.interrupt("the Esc key")
    await asyncio.wait_for(task, 1.0)
    assert h.audio.stop_count >= 1
    assert_history_valid(h.agent.session.messages)
    assert h.face.state.expression == "listening"

    h.client.script = [reply()]
    await h.agent.handle(utterance("stop"))
    note = h.client.requests[-1]["messages"][-1]["content"]
    note_text = " ".join(b.get("text", "") for b in note if b.get("type") == "text")
    assert 'They heard: "The first sentence is here."' in note_text
    assert 'They did not hear: "The second never gets said."' in note_text
    assert "the Esc key" in note_text


async def test_interrupt_while_thinking_cancels_the_request() -> None:
    h = make_harness()
    h.client.script = [Slow(reply(tool_use("speak", text="Too late.")), delay=5.0)]
    task = asyncio.create_task(h.agent.handle(utterance("question")))
    await _wait_until(lambda: len(h.client.requests) == 1)
    await asyncio.sleep(0.01)
    h.agent.interrupt("the stop button")
    await asyncio.wait_for(task, 1.0)  # well under the 5 s the stream would take
    assert h.spoken_texts == []
    assert [m["role"] for m in h.agent.session.messages] == ["user"]
    h.client.script = [reply()]
    await h.agent.handle(utterance("never mind"))
    first = h.client.requests[-1]["messages"][0]["content"]
    assert any("They heard nothing" in b.get("text", "") for b in first)


async def test_interrupt_with_nothing_running_just_stops_audio(harness: AgentHarness) -> None:
    harness.agent.interrupt("the Esc key")
    assert harness.audio.stop_count == 1
    assert not harness.agent.busy
