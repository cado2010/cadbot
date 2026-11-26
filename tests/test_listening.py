# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""VAD segmentation, the half-duplex mic, barge-in, and the real Silero model."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from cadbot.bus import EventBus, Utterance
from cadbot.sensors.listener import Listener, ListenerHooks
from cadbot.sensors.stop_phrases import match_stop_phrase
from cadbot.sensors.stt import Transcript
from cadbot.sensors.vad import (
    FRAME,
    FRAME_MS,
    SegmenterConfig,
    SileroVad,
    SpeechDiscarded,
    SpeechEnd,
    SpeechSegmenter,
    SpeechStart,
)

SILENCE, SPEECH = 0.02, 0.9


def frames(n: int, value: float = 0.0) -> list[np.ndarray]:
    return [np.full(FRAME, value, dtype=np.float32) for _ in range(n)]


def run(seg: SpeechSegmenter, probs: list[float]) -> list[object]:
    events: list[object] = []
    for p in probs:
        events += seg.push(np.full(FRAME, p, dtype=np.float32), p)
    return events


def test_turn_ends_after_700ms_silence() -> None:
    seg = SpeechSegmenter(SegmenterConfig())
    speech_frames = 30  # ~1 s
    silence_needed = -(-700 // FRAME_MS)
    events = run(seg, [SILENCE] * 5 + [SPEECH] * speech_frames + [SILENCE] * (silence_needed - 1))
    assert isinstance(events[0], SpeechStart) and len(events) == 1
    events = run(seg, [SILENCE])
    assert len(events) == 1 and isinstance(events[0], SpeechEnd)
    end = events[0]
    assert abs(end.speech_s - speech_frames * FRAME_MS / 1000) < 0.05
    # pre-roll (300 ms) is kept in front, most trailing silence is dropped
    assert end.audio.size // FRAME < 9 + speech_frames + silence_needed


def test_short_blips_are_discarded() -> None:
    seg = SpeechSegmenter(SegmenterConfig())
    events = run(seg, [SPEECH] * 3 + [SILENCE] * 30)
    assert isinstance(events[0], SpeechStart) and isinstance(events[-1], SpeechDiscarded)


def test_long_speech_is_cut_at_max_length() -> None:
    seg = SpeechSegmenter(SegmenterConfig(max_utterance_s=1.0))
    events = run(seg, [SPEECH] * 40)
    assert any(isinstance(e, SpeechEnd) for e in events)


def test_silero_model_runs_on_silence() -> None:
    vad = SileroVad()
    probs = [vad(f) for f in frames(10)]
    assert all(0.0 <= p < 0.5 for p in probs)


class FakeSpeechState:
    def __init__(self) -> None:
        self.speaking = False
        self.current_text = ""

    def recently_spoke(self, tail_s: float) -> bool:
        return self.speaking


class FakeSTT:
    def __init__(self, text: str = "what's the weather") -> None:
        self.text = text

    def transcribe(self, audio: np.ndarray) -> Transcript | None:
        return Transcript(self.text, "en")


def make_listener(echo_cancellation: bool, hooks: ListenerHooks | None = None,
                  heard: str = "what's the weather",
                  ) -> tuple[Listener, EventBus, FakeSpeechState]:
    bus = EventBus()
    state = FakeSpeechState()
    listener = Listener(
        audio_in=None,  # type: ignore[arg-type]  # process() is driven directly
        vad=lambda frame: float(frame[0]), segmenter=SpeechSegmenter(SegmenterConfig()),
        stt=FakeSTT(heard), bus=bus, speech_state=state, echo_cancellation=echo_cancellation,
        hooks=hooks)
    return listener, bus, state


async def test_utterance_reaches_the_bus() -> None:
    listener, bus, _ = make_listener(echo_cancellation=False)
    for f in frames(20, SPEECH) + frames(30, SILENCE):
        listener.process(f)
    event = await asyncio.wait_for(bus.get(), 2)
    assert isinstance(event, Utterance) and event.text == "what's the weather"


async def test_half_duplex_ignores_the_mic_while_speaking() -> None:
    starts: list[int] = []
    listener, bus, state = make_listener(
        echo_cancellation=False, hooks=ListenerHooks(on_speech_start=lambda: starts.append(1)))
    state.speaking = True
    for f in frames(20, SPEECH) + frames(30, SILENCE):
        listener.process(f)
    await asyncio.sleep(0.05)
    assert starts == [] and bus.empty()


async def test_barge_in_with_echo_cancellation() -> None:
    barged: list[int] = []
    listener, bus, state = make_listener(
        echo_cancellation=True, hooks=ListenerHooks(on_barge_in=lambda: barged.append(1)))
    state.speaking = True
    for f in frames(int(0.5 * 1000 / FRAME_MS), SPEECH):
        listener.process(f)
    assert barged == [1]
    state.speaking = False
    for f in frames(30, SILENCE):
        listener.process(f)
    event = await asyncio.wait_for(bus.get(), 2)
    assert isinstance(event, Utterance) and event.during_speech


# ----------------------------------------------------------------------- "stop" while speaking


@pytest.mark.parametrize(("heard", "phrase"), [
    ("Stop.", "stop"), ("Never mind!", "never mind"), ("cadbot, stop", "stop"),
    ("OK, stop it please", "stop it"), ("Hold on", "hold on"), ("That's enough.", "that's enough"),
    ("Okay cadbot, be quiet", "be quiet"), ("Wait, what was that?", "wait"),
])
def test_stop_phrases_are_recognised(heard: str, phrase: str) -> None:
    assert match_stop_phrase(heard) == phrase


@pytest.mark.parametrize("heard", [
    "what's the weather", "please don't stop the music now ok", "the bus stop is close",
    "I can't wait to see what happens tomorrow at the park", "",
])
def test_ordinary_speech_is_not_a_stop(heard: str) -> None:
    assert match_stop_phrase(heard) is None


def test_its_own_voice_is_not_a_stop() -> None:
    # through speakers, cadbot may hear itself say "never mind"
    assert match_stop_phrase("never mind", speaking="Never mind, I found it.") is None
    assert match_stop_phrase("stop", speaking="It's the next stop on the line.") is None


async def test_saying_stop_interrupts_even_with_the_mic_muted() -> None:
    stops: list[str] = []
    listener, bus, state = make_listener(
        echo_cancellation=False, heard="Stop!",
        hooks=ListenerHooks(on_stop_phrase=stops.append))
    state.speaking = True
    state.current_text = "Saturday looks sunny, around sixty degrees."
    for f in frames(15, SPEECH) + frames(15, SILENCE):  # half a second of "stop"
        listener.process(f)
    event = await asyncio.wait_for(bus.get(), 2)
    assert stops == ["Stop!"]
    assert isinstance(event, Utterance) and event.text == "Stop!" and event.during_speech


async def test_other_talk_while_muted_is_still_ignored() -> None:
    stops: list[str] = []
    listener, bus, state = make_listener(
        echo_cancellation=False, heard="the weather is lovely",
        hooks=ListenerHooks(on_stop_phrase=stops.append))
    state.speaking = True
    for f in frames(15, SPEECH) + frames(15, SILENCE):
        listener.process(f)
    await asyncio.sleep(0.05)
    assert stops == [] and bus.empty()


async def test_long_speech_while_muted_is_not_checked() -> None:
    """cadbot's own sentences through speakers are long: they aren't even transcribed."""
    calls: list[int] = []
    listener, bus, state = make_listener(echo_cancellation=False, heard="stop")
    original = listener.stt.transcribe

    def counting(audio: np.ndarray) -> object:
        calls.append(1)
        return original(audio)

    listener.stt.transcribe = counting  # type: ignore[method-assign]
    state.speaking = True
    for f in frames(int(2.4 * 1000 / FRAME_MS), SPEECH) + frames(15, SILENCE):
        listener.process(f)
    await asyncio.sleep(0.05)
    assert calls == [] and bus.empty()


async def test_stop_phrases_can_be_turned_off() -> None:
    listener, bus, state = make_listener(echo_cancellation=False, heard="stop")
    listener.stop_phrases = ()
    state.speaking = True
    for f in frames(15, SPEECH) + frames(15, SILENCE):
        listener.process(f)
    await asyncio.sleep(0.05)
    assert bus.empty()
