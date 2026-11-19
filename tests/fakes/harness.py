# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Builds a full Agent on fake hardware and a fake Claude, for tests."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from cadbot.actuators.canned import CannedClips
from cadbot.actuators.speech import SpeechOutput
from cadbot.agent.loop import Agent
from cadbot.agent.prompt import build_system_prompt
from cadbot.agent.tools import build_registry
from cadbot.agent.tools.registry import ToolContext, TurnState
from cadbot.bus import Utterance
from cadbot.config import AgentConfig, VisionConfig
from cadbot.face.renderer import Face
from cadbot.net.health import HealthMonitor
from cadbot.people.registry import PeopleRegistry
from cadbot.people.store import PeopleStore
from cadbot.platform.base import Capabilities
from cadbot.platform.common.pygame_display import PygameDisplay
from cadbot.platform.fake.audio import FakeAudioOut
from cadbot.vision.loop import VisionLoop
from tests.fakes.claude import FakeClaudeClient
from tests.fakes.vision import FakeAnalyzer, FakeReader

SAMPLE_RATE = 16_000


class FakeTTS:
    """0.1 s of quiet tone per word, so durations scale with text length."""

    def __init__(self, languages: tuple[str, ...] = ("en",)) -> None:
        self._languages = list(languages)
        self.calls: list[tuple[str, str]] = []

    def languages(self) -> list[str]:
        return self._languages

    def synthesize(self, text: str, lang: str) -> tuple[np.ndarray, int]:
        self.calls.append((text, lang))
        n = int(SAMPLE_RATE * 0.1 * max(1, len(text.split())))
        return (0.1 * np.sin(np.arange(n) / 10)).astype(np.float32), SAMPLE_RATE


class FakeNotifier:
    def __init__(self) -> None:
        self.alerts: list[str] = []

    async def alert(self, text: str) -> None:
        self.alerts.append(text)


@dataclass
class AgentHarness:
    agent: Agent
    client: FakeClaudeClient
    tts: FakeTTS
    audio: FakeAudioOut
    speech: SpeechOutput
    face: Face
    canned: CannedClips
    health: HealthMonitor
    notifier: FakeNotifier
    probe_result: list[bool]
    sleeps: list[float] = field(default_factory=list)
    vision: VisionLoop | None = None
    people: PeopleRegistry | None = None
    reader: FakeReader | None = None
    analyzer: FakeAnalyzer | None = None

    @property
    def spoken_texts(self) -> list[str]:
        return [t for t, _ in self.tts.calls]


def utterance(text: str) -> Utterance:
    return Utterance(text=text, started_at=datetime(2026, 11, 19, 14, 30), duration_s=1.5)


def make_vision() -> tuple[VisionLoop, PeopleRegistry, FakeReader, FakeAnalyzer]:
    folder = Path(tempfile.mkdtemp(prefix="cadbot-test-"))
    people = PeopleRegistry(PeopleStore(folder / "cadbot.db", folder / "faces"), VisionConfig())
    reader, analyzer = FakeReader(), FakeAnalyzer()
    vision = VisionLoop(reader=reader, analyzer=analyzer,  # type: ignore[arg-type]
                        people=people, config=VisionConfig(), emit=lambda _o: None)
    return vision, people, reader, analyzer


def make_harness(*, audio_speed: float = 0.0, config: AgentConfig | None = None,
                 with_vision: bool = False) -> AgentHarness:
    config = config or AgentConfig()
    vision = people = reader = analyzer = None
    if with_vision:
        vision, people, reader, analyzer = make_vision()
    client = FakeClaudeClient()
    tts = FakeTTS()
    audio = FakeAudioOut(speed=audio_speed)
    speech = SpeechOutput(tts, audio)
    face = Face(PygameDisplay(fullscreen=False, video_driver="dummy"), level=speech.level)
    canned = CannedClips(tts, speech, min_interval_s=60)
    probe_result = [True]

    async def probe() -> bool:
        return probe_result[0]

    health = HealthMonitor(probe, failures_before_offline=2)
    registry = build_registry(config)
    caps = Capabilities(keyboard=True)
    notifier = FakeNotifier()
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def make_context(turn: TurnState) -> ToolContext:
        return ToolContext(speech=speech, face=face, capabilities=caps, config=config,
                           registry=registry, turn=turn, vision=vision, people=people)

    agent = Agent(client=client, registry=registry, config=config,
                  system_prompt=build_system_prompt(caps, "fake"), make_context=make_context,
                  face=face, speech=speech, canned=canned, health=health, notifier=notifier,
                  sleep=fake_sleep)
    return AgentHarness(agent, client, tts, audio, speech, face, canned, health, notifier,
                        probe_result, sleeps, vision, people, reader, analyzer)
