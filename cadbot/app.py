# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Starts cadbot: wires sensors, the agent and actuators together, and runs them as tasks."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import logging.handlers
import sys
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import truststore

from cadbot import __version__
from cadbot.actuators.canned import CannedClips
from cadbot.actuators.notify import LogNotifier
from cadbot.actuators.speech import SpeechOutput
from cadbot.actuators.tts import PiperTTS
from cadbot.agent.client import AnthropicClient
from cadbot.agent.loop import Agent
from cadbot.agent.prompt import build_system_prompt
from cadbot.agent.tools import build_registry
from cadbot.agent.tools.registry import ToolContext, TurnState
from cadbot.bus import BackOnline, EventBus
from cadbot.config import Config, load_config
from cadbot.face.renderer import Face
from cadbot.models import voice_files, whisper_dir
from cadbot.models.download import check
from cadbot.net.health import HealthMonitor, https_probe
from cadbot.people.registry import PeopleRegistry
from cadbot.people.store import PeopleStore
from cadbot.platform import Platform, get_platform
from cadbot.sensors.listener import Listener, ListenerHooks
from cadbot.sensors.stt import WhisperTranscriber
from cadbot.sensors.vad import SegmenterConfig, SileroVad, SpeechSegmenter
from cadbot.vision.faces import SFACE, YUNET, YuNetSFace
from cadbot.vision.loop import FrameReader, VisionLoop

log = logging.getLogger("cadbot")


def setup_logging(logs_dir: Path | None, verbose: bool) -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)
    if logs_dir is not None:
        file = logging.handlers.RotatingFileHandler(logs_dir / "cadbot.log", maxBytes=1_000_000,
                                                    backupCount=3, encoding="utf-8")
        file.setFormatter(fmt)
        root.addHandler(file)
    for noisy in ("httpx", "httpx2", "httpcore", "anthropic", "faster_whisper", "piper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def segmenter_config(config: Config) -> SegmenterConfig:
    a = config.audio
    return SegmenterConfig(threshold=a.vad_threshold, end_silence_ms=a.end_silence_ms,
                           min_speech_ms=a.min_speech_ms, max_utterance_s=a.max_utterance_s,
                           pre_roll_ms=a.pre_roll_ms)


def missing_models(models_dir: Path) -> list[str]:
    return [s.entry.dest for s in check(models_dir, verify_hash=False)
            if s.state != "ok" and s.entry.group in ("whisper", "voice:en")]


@dataclass
class Runtime:
    stop: asyncio.Event
    tasks: list[asyncio.Task[Any]]

    def spawn(self, coro: Coroutine[Any, Any, Any], name: str) -> None:
        task = asyncio.create_task(coro, name=name)
        task.add_done_callback(self._on_done)
        self.tasks.append(task)

    def _on_done(self, task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            return
        if task.exception() is not None:
            log.error("task %s crashed", task.get_name(), exc_info=task.exception())
            self.stop.set()


async def run_app(platform: Platform, config: Config, api_key: str) -> int:
    models_dir = platform.paths.models_dir
    display = platform.display()
    display.open()
    audio_out = platform.audio_out(config.audio.output_device)
    await audio_out.start()
    tts = PiperTTS(voice_files(models_dir))
    speech = SpeechOutput(tts, audio_out)
    face = Face(display, level=speech.level, fps=config.face.fps)
    canned = CannedClips(tts, speech, config.net.canned_min_interval_s)
    registry = build_registry(config.agent)
    bus = EventBus()
    runtime = Runtime(asyncio.Event(), [])
    agent: Agent

    def on_health_change(online: bool, since: datetime) -> None:
        if not online:
            face.set_status("offline")
            face.set("sleepy")
            return
        face.set_status(None)
        face.apply_preset("idle")
        missed = agent.take_missed()
        if missed:
            bus.put_nowait(BackOnline(since=since, missed=missed))

    health = HealthMonitor(https_probe(config.net.health_url),
                           interval_s=config.net.health_interval_s,
                           failures_before_offline=config.net.failures_before_offline,
                           on_change=on_health_change)
    system_prompt = build_system_prompt(platform.capabilities, platform.name,
                                        config.household.wishes, camera=camera_mode(config))

    people = open_people(platform, config)
    vision = make_vision(platform, config, people, bus)
    if vision is not None:
        vision.on_gaze = face.set_gaze_point
    listener: Listener | None = None

    def make_context(turn: TurnState) -> ToolContext:
        return ToolContext(speech=speech, face=face, capabilities=platform.capabilities,
                           config=config.agent, registry=registry, turn=turn, vision=vision,
                           people=people if vision is not None else None, listener=listener)

    client = AnthropicClient(api_key, config.agent.request_timeout_s)
    agent = Agent(client=client, registry=registry, config=config.agent,
                  system_prompt=system_prompt, make_context=make_context, face=face,
                  speech=speech, canned=canned, health=health, notifier=LogNotifier())
    agent.idle_after_s = config.face.idle_after_speech_s
    face.callbacks.on_stop = lambda: agent.interrupt("the stop button or the Esc key")
    face.callbacks.on_quit = runtime.stop.set

    log.info("loading Whisper %s ...", config.stt.model)
    stt = WhisperTranscriber(whisper_dir(models_dir), config.stt)
    await asyncio.to_thread(stt.load)

    def on_speech_start() -> None:
        if not agent.busy:
            face.apply_preset("listening")

    listener = Listener(
        audio_in=platform.audio_in(config.audio.input_device), vad=SileroVad(),
        segmenter=SpeechSegmenter(segmenter_config(config)), stt=stt, bus=bus,
        speech_state=speech, echo_cancellation=platform.capabilities.echo_cancellation,
        half_duplex_tail_s=config.audio.half_duplex_tail_ms / 1000,
        barge_in_min_s=config.audio.barge_in_min_s,
        hooks=ListenerHooks(
            on_speech_start=on_speech_start,
            on_speech_discarded=lambda: None if agent.busy else face.schedule_preset("idle", 0.5),
            on_barge_in=lambda: agent.interrupt("their voice"),
        ),
        snapshot=vision.snapshot if vision is not None else lambda: None)

    runtime.spawn(face.run(), "face")
    runtime.spawn(canned.render_all(), "canned")
    runtime.spawn(listener.run(), "listener")
    runtime.spawn(agent.run(bus), "agent")
    runtime.spawn(health.run(), "health")
    if vision is not None:
        runtime.spawn(_run_vision(vision), "vision")
    runtime.spawn(_watchdog(platform), "watchdog")
    platform.lifecycle.notify_ready()
    log.info("cadbot %s is listening (platform %s). Esc stops speech; close the window to quit.",
             __version__, platform.name)
    try:
        await runtime.stop.wait()
    finally:
        platform.lifecycle.notify_stopping()
        for task in runtime.tasks:
            task.cancel()
        await asyncio.gather(*runtime.tasks, return_exceptions=True)
        with contextlib.suppress(Exception):
            await client.close()
        await audio_out.close()
        display.close()
        people.store.close()
    return 0


def camera_mode(config: Config) -> str:
    return config.vision.send_to_claude if config.vision.enabled else "off"


def open_people(platform: Platform, config: Config) -> PeopleRegistry:
    data = platform.paths.data_dir
    registry = PeopleRegistry(PeopleStore(data / "cadbot.db", data / "faces"), config.vision)
    registry.load()
    return registry


def make_vision(platform: Platform, config: Config, people: PeopleRegistry,
                bus: EventBus) -> VisionLoop | None:
    if not config.vision.enabled or not platform.capabilities.camera:
        log.info("camera disabled")
        return None
    models = platform.paths.models_dir
    analyzer = None
    if (models / YUNET).is_file() and (models / SFACE).is_file():
        analyzer = YuNetSFace(models, min_face_px=config.vision.min_face_px)
    else:
        log.warning("face models missing; run `python -m cadbot.models ensure`. "
                    "The camera works, but nobody will be recognised.")
    reader = FrameReader(platform.camera(config.vision.camera_index))
    return VisionLoop(reader=reader, analyzer=analyzer, people=people, config=config.vision,
                      emit=bus.put_nowait)


async def _run_vision(vision: VisionLoop) -> None:
    """A camera failure shouldn't take cadbot down: it keeps listening and talking."""
    try:
        await vision.run()
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("camera stopped; carrying on without it")


async def _watchdog(platform: Platform) -> None:
    while True:
        platform.lifecycle.watchdog_ping()
        await asyncio.sleep(10)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cadbot", description="Run cadbot.")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="debug logging, including what cadbot hears")
    args = parser.parse_args(argv)
    truststore.inject_into_ssl()  # use the OS certificate store (proxies, antivirus TLS)
    platform = get_platform()
    setup_logging(platform.paths.logs_dir, args.verbose)
    config = load_config(platform.name, platform.paths.config_dir)
    api_key = platform.paths.get_secret("ANTHROPIC_API_KEY")
    if not api_key:
        log.error("ANTHROPIC_API_KEY is not set. Put it in .env (see .env.example).")
        return 2
    missing = missing_models(platform.paths.models_dir)
    if missing:
        log.error("missing model files (%s). Run: uv run python -m cadbot.models ensure",
                  ", ".join(missing))
        return 2
    try:
        return asyncio.run(run_app(platform, config, api_key))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
