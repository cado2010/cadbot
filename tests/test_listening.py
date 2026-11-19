# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""VAD segmentation, the half-duplex mic, barge-in, and the real Silero model."""

from __future__ import annotations

import asyncio

import numpy as np

from cadbot.bus import EventBus, Utterance
from cadbot.sensors.listener import Listener, ListenerHooks
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

    def recently_spoke(self, tail_s: float) -> bool:
        return self.speaking


class FakeSTT:
    def transcribe(self, audio: np.ndarray) -> Transcript | None:
        return Transcript("what's the weather", "en")


def make_listener(echo_cancellation: bool, hooks: ListenerHooks | None = None,
                  ) -> tuple[Listener, EventBus, FakeSpeechState]:
    bus = EventBus()
    state = FakeSpeechState()
    listener = Listener(
        audio_in=None,  # type: ignore[arg-type]  # process() is driven directly
        vad=lambda frame: float(frame[0]), segmenter=SpeechSegmenter(SegmenterConfig()),
        stt=FakeSTT(), bus=bus, speech_state=state, echo_cancellation=echo_cancellation,
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
