# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""python -m cadbot.selftest --offline | --hardware | --api

--offline   config, model files (hashes), VAD, Piper and Whisper (Whisper transcribes Piper)
--hardware  camera image, 3 s mic recording played back, the face window
--api       one short reply from Claude (checks the key, model access and spend limit)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
import traceback
from collections.abc import Awaitable, Callable

import numpy as np
import truststore

from cadbot.config import load_config
from cadbot.platform import AUDIO_SAMPLE_RATE, Platform, get_platform

Check = Callable[[Platform], Awaitable[str]]


async def check_config(platform: Platform) -> str:
    config = load_config(platform.name, platform.paths.config_dir)
    return f"platform={platform.name}, model={config.agent.model}, effort={config.agent.effort}"


async def check_models(platform: Platform) -> str:
    from cadbot.models.download import check

    statuses = await asyncio.to_thread(check, platform.paths.models_dir)
    bad = [f"{s.entry.dest} ({s.state})" for s in statuses if s.state != "ok"]
    if bad:
        raise RuntimeError("run `python -m cadbot.models ensure`: " + ", ".join(bad))
    return f"{len(statuses)} files verified in {platform.paths.models_dir}"


async def check_vad(_platform: Platform) -> str:
    from cadbot.sensors.vad import FRAME, SileroVad

    vad = SileroVad()
    prob = vad(np.zeros(FRAME, dtype=np.float32))
    if prob > 0.5:
        raise RuntimeError(f"silence scored as speech ({prob:.2f})")
    return f"Silero VAD loaded; silence -> {prob:.3f}"


async def check_speech_round_trip(platform: Platform) -> str:
    from cadbot.actuators.tts import PiperTTS
    from cadbot.models import voice_files, whisper_dir
    from cadbot.platform.common.audio_math import resample
    from cadbot.sensors.stt import WhisperTranscriber

    config = load_config(platform.name, platform.paths.config_dir)
    tts = PiperTTS(voice_files(platform.paths.models_dir))
    t0 = time.perf_counter()
    audio, rate = await asyncio.to_thread(tts.synthesize, "Hello, how is the weather today?", "en")
    t_tts = time.perf_counter() - t0
    stt = WhisperTranscriber(whisper_dir(platform.paths.models_dir), config.stt)
    await asyncio.to_thread(stt.load)
    t0 = time.perf_counter()
    transcript = await asyncio.to_thread(stt.transcribe, resample(audio, rate, AUDIO_SAMPLE_RATE))
    t_stt = time.perf_counter() - t0
    text = transcript.text if transcript else ""
    if "weather" not in text.lower():
        raise RuntimeError(f"Whisper heard {text!r}")
    return (f"Piper {t_tts:.2f}s -> Whisper ({stt.device}) {t_stt:.2f}s heard {text!r}")


async def check_api_key_present(platform: Platform) -> str:
    if not platform.paths.get_secret("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY not found (environment or .env)")
    return "ANTHROPIC_API_KEY found (not checked; use --api)"


async def check_camera(platform: Platform) -> str:
    camera = platform.camera()
    camera.open()
    try:
        frames = [f for _ in range(15) if (f := camera.read()) is not None]
    finally:
        camera.close()
    if not frames:
        raise RuntimeError("no frames from the camera")
    h, w = frames[-1].image.shape[:2]
    _show_frame(platform, frames[-1].image)
    return f"{len(frames)}/15 frames, {w}x{h}, night={frames[-1].is_night}"


def _show_frame(platform: Platform, image: np.ndarray) -> None:
    import pygame

    display = platform.display()
    display.open()
    try:
        rgb = np.ascontiguousarray(image[..., ::-1])
        surface = pygame.surfarray.make_surface(rgb.swapaxes(0, 1))
        pygame.transform.smoothscale(surface, display.surface.get_size(), display.surface)
        display.present()
        end = time.monotonic() + 3
        while time.monotonic() < end:
            display.poll_events()
            time.sleep(0.05)
    finally:
        display.close()


async def check_audio(platform: Platform) -> str:
    config = load_config(platform.name, platform.paths.config_dir)
    mic = platform.audio_in(config.audio.input_device)
    speaker = platform.audio_out(config.audio.output_device)
    print("    recording 3 seconds: say something...", flush=True)
    await mic.start()
    chunks: list[np.ndarray] = []
    try:
        async with asyncio.timeout(10):
            async for chunk in mic.chunks():
                chunks.append(chunk.samples)
                if len(chunks) * chunk.samples.size >= 3 * AUDIO_SAMPLE_RATE:
                    break
    finally:
        await mic.stop()
    audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    print("    playing it back...", flush=True)
    await speaker.start()
    try:
        await speaker.play(audio, AUDIO_SAMPLE_RATE)
    finally:
        await speaker.close()
    if peak < 0.01:
        raise RuntimeError(f"the recording was silent (peak {peak:.3f}); check the mic")
    return f"recorded {audio.size / AUDIO_SAMPLE_RATE:.1f}s, peak level {peak:.2f}"


async def check_face(platform: Platform) -> str:
    from cadbot.face.expressions import EXPRESSIONS
    from cadbot.face.renderer import Face

    display = platform.display()
    display.open()
    try:
        face = Face(display)
        for name in EXPRESSIONS:
            face.set(name)
            end = time.monotonic() + 0.6
            while time.monotonic() < end:
                face.tick()
                await asyncio.sleep(1 / 30)
    finally:
        display.close()
    return f"showed {len(EXPRESSIONS)} expressions"


async def check_api(platform: Platform) -> str:
    from cadbot.agent.client import AnthropicClient

    config = load_config(platform.name, platform.paths.config_dir)
    key = platform.paths.get_secret("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not found (environment or .env)")
    client = AnthropicClient(key, 60)
    t0 = time.perf_counter()
    try:
        async with client.stream(
            model=config.agent.model, max_tokens=1000,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": "Reply with the single word: ready"}],
        ) as stream:
            message = await stream.get_final_message()
    finally:
        await client.close()
    text = " ".join(b.text for b in message.content if b.type == "text").strip()
    usage = message.usage
    return (f"{config.agent.model} replied {text!r} in {time.perf_counter() - t0:.1f}s "
            f"({usage.input_tokens} in / {usage.output_tokens} out tokens)")


async def check_agent_request(platform: Platform) -> str:
    """One request with cadbot's real agent settings: system prompt, tools, web search,
    effort, fallbacks and caching. Expects Claude to answer through the speak tool."""
    from cadbot.agent.client import AnthropicClient
    from cadbot.agent.loop import FALLBACK_BETA
    from cadbot.agent.prompt import build_system_prompt
    from cadbot.agent.tools import build_registry

    config = load_config(platform.name, platform.paths.config_dir)
    key = platform.paths.get_secret("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not found (environment or .env)")
    params = {
        "model": config.agent.model, "max_tokens": config.agent.max_tokens,
        "system": [{"type": "text", "cache_control": {"type": "ephemeral"},
                    "text": build_system_prompt(platform.capabilities, platform.name)}],
        "tools": build_registry(config.agent).api_definitions(),
        "output_config": {"effort": config.agent.effort},
        "cache_control": {"type": "ephemeral"},
        "messages": [{"role": "user", "content": [{"type": "text", "text":
                      '[utterance] Heard (1.0 s): "cadbot, can you hear me? Just say yes."'}]}],
    }
    if config.agent.fallbacks == "default":
        params |= {"betas": [FALLBACK_BETA], "fallbacks": "default"}
    client = AnthropicClient(key, 60)
    t0 = time.perf_counter()
    try:
        async with client.stream(**params) as stream:
            message = await stream.get_final_message()
    finally:
        await client.close()
    calls = [f"{b.name}({b.input})" for b in message.content if b.type == "tool_use"]
    if not any(c.startswith("speak(") for c in calls):
        raise RuntimeError(f"expected a speak() call; got {calls or message.stop_reason}")
    return f"{time.perf_counter() - t0:.1f}s, tool calls: {'; '.join(calls)}"


SUITES: dict[str, list[tuple[str, Check]]] = {
    "offline": [("config", check_config), ("models", check_models), ("vad", check_vad),
                ("piper -> whisper", check_speech_round_trip),
                ("api key", check_api_key_present)],
    "hardware": [("camera", check_camera), ("mic + speaker", check_audio),
                 ("face window", check_face)],
    "api": [("claude", check_api), ("agent request", check_agent_request)],
}


async def run_suite(name: str, platform: Platform) -> bool:
    print(f"== {name}")
    ok = True
    for label, check in SUITES[name]:
        try:
            detail = await check(platform)
            print(f"  PASS {label}: {detail}")
        except Exception as exc:
            ok = False
            print(f"  FAIL {label}: {type(exc).__name__}: {exc}")
            logging.debug("".join(traceback.format_exception(exc)))
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cadbot.selftest")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--hardware", action="store_true")
    parser.add_argument("--api", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    suites = [s for s in ("offline", "hardware", "api") if getattr(args, s)] or ["offline"]
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    truststore.inject_into_ssl()
    platform = get_platform()

    async def run_all() -> bool:
        results = [await run_suite(s, platform) for s in suites]
        return all(results)

    ok = asyncio.run(run_all())
    print("ALL PASSED" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
