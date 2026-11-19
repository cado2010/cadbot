# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Speech output: sentence streaming, stopping, canned clips."""

from __future__ import annotations

import asyncio

from cadbot.actuators.canned import CANNED, CannedClips
from cadbot.actuators.speech import SpeechOutput, SpeechResult, clean_for_speech, split_sentences
from cadbot.platform.fake.audio import FakeAudioOut
from tests.fakes.harness import FakeTTS


def test_sentence_split() -> None:
    assert split_sentences("It's sunny today. Around sixty degrees! Want the details?") == [
        "It's sunny today.", "Around sixty degrees!", "Want the details?"]
    assert split_sentences("Hi. Okay. Here is a longer one.") == [
        "Hi. Okay. Here is a longer one."]  # fragments are joined until long enough
    assert split_sentences("  ") == []


def test_markdown_is_removed() -> None:
    assert clean_for_speech("**Sunny**, `about` 60 #today") == "Sunny, about 60 today"


async def test_speaks_each_sentence_in_order() -> None:
    tts, audio = FakeTTS(), FakeAudioOut(speed=0)
    speech = SpeechOutput(tts, audio)
    result = await speech.speak("First one here. Second one here.")
    assert [t for t, _ in tts.calls] == ["First one here.", "Second one here."]
    assert len(audio.played) == 2
    assert result.spoken == ["First one here.", "Second one here."] and not result.interrupted


async def test_stop_reports_what_was_heard() -> None:
    tts, audio = FakeTTS(), FakeAudioOut(speed=1.0)
    speech = SpeechOutput(tts, audio)
    result = SpeechResult()
    task = asyncio.create_task(speech.speak("First one here. Second one here.", result=result))
    while len(audio.played) < 1:
        await asyncio.sleep(0.01)
    speech.stop()
    await asyncio.wait_for(task, 1)
    assert result.interrupted
    assert result.spoken == ["First one here."] and result.unspoken == ["Second one here."]
    assert not speech.speaking


async def test_speaking_state_callbacks() -> None:
    events: list[str] = []
    speech = SpeechOutput(FakeTTS(), FakeAudioOut(speed=0))
    speech.on_start = lambda: events.append("start")
    speech.on_end = lambda: events.append("end")
    await speech.speak("Hello there, friend.")
    assert events == ["start", "end"]
    assert speech.recently_spoke(10.0) and not speech.recently_spoke(0.0)


async def test_canned_clips_are_rate_limited() -> None:
    tts, audio = FakeTTS(), FakeAudioOut(speed=0)
    clips = CannedClips(tts, SpeechOutput(tts, audio), min_interval_s=60)
    await clips.render_all()
    assert len(tts.calls) == len(CANNED)
    assert await clips.play("offline") is True
    assert await clips.play("offline") is False  # at most once a minute
    assert await clips.play("one_moment", rate_limited=False) is True
    assert len(audio.played) == 2
