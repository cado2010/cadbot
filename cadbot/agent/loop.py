# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""The agent: every event becomes a user message; Claude acts only through tool calls.

Fixed in code (not Claude's decision): the canned replies when Claude can't be reached,
retries, and stopping at once when interrupted.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from cadbot.actuators.canned import CannedClips
from cadbot.actuators.notify import OwnerNotifier
from cadbot.actuators.speech import SpeechOutput
from cadbot.agent.client import ClaudeClient
from cadbot.agent.errors import (
    CANNED_KEY,
    NEEDS_OWNER,
    RETRYABLE,
    ClaudeFailure,
    ErrorKind,
    classify,
)
from cadbot.agent.executor import ToolExecutor
from cadbot.agent.session import Session
from cadbot.agent.tools.registry import ConversationState, ToolContext, ToolRegistry, TurnState
from cadbot.bus import Event, EventBus, Observation, Utterance
from cadbot.config import AgentConfig
from cadbot.face.renderer import Face
from cadbot.net.health import HealthMonitor
from cadbot.router import render_event
from cadbot.usage import UsageLog

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
COMPACTION_BETA = "compact-2026-01-12"
MAX_RETRY_DELAY_S = 10.0


def request_params(cfg: AgentConfig, system_prompt: str, tools: list[dict[str, Any]],
                   messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Every request cadbot sends to Claude (also used by `selftest --api`)."""
    params: dict[str, Any] = {
        "model": cfg.model,
        "max_tokens": cfg.max_tokens,
        "system": [{"type": "text", "text": system_prompt,
                    "cache_control": {"type": "ephemeral"}}],
        "tools": tools,
        "messages": messages,
        "output_config": {"effort": cfg.effort},
        "cache_control": {"type": "ephemeral"},
        # Server-side compaction keeps image-heavy sessions bounded and the history
        # append-only (safe with Opus 5.5's preserved thinking).
        "context_management": {"edits": [{
            "type": "compact_20260112",
            "trigger": {"type": "input_tokens", "value": cfg.compact_at_tokens}}]},
    }
    betas = [COMPACTION_BETA]
    if cfg.fallbacks == "default":
        betas.append(FALLBACK_BETA)
        params["fallbacks"] = "default"
    params["betas"] = betas
    return params


class Agent:
    def __init__(self, *, client: ClaudeClient, registry: ToolRegistry, config: AgentConfig,
                 system_prompt: str, make_context: Callable[[TurnState], ToolContext],
                 face: Face, speech: SpeechOutput, canned: CannedClips, health: HealthMonitor,
                 notifier: OwnerNotifier, session: Session | None = None,
                 usage_log: UsageLog | None = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.client = client
        self.registry = registry
        self.cfg = config
        self.system_prompt = system_prompt
        self.make_context = make_context
        self.face = face
        self.speech = speech
        self.canned = canned
        self.health = health
        self.notifier = notifier
        self.session = session or Session()
        self.usage_log = usage_log
        self.place: Callable[[], str | None] = lambda: None
        """Where the device is (city, region), added to every event."""
        self.sleep = sleep
        self._notes: list[str] = []
        self._missed: list[Utterance] = []
        self._current: tuple[asyncio.Task[None], TurnState] | None = None
        self._interrupt_source: str | None = None
        self._offline_key = "offline"
        self.conversation = ConversationState()
        self.idle_after_s = 2.5

    # ------------------------------------------------------------------ event intake

    async def run(self, bus: EventBus) -> None:
        while True:
            await self.handle(await bus.get())

    async def handle(self, event: Event) -> None:
        if not self.health.online:
            if isinstance(event, Utterance):
                self._missed.append(event)
                await self.canned.play(self._offline_key)
            return  # camera frames are dropped while offline
        if isinstance(event, Utterance):
            self.conversation.utterance_seq += 1
            self.conversation.last_utterance = event.text
        content = render_event(event, self._take_notes(), place=self.place())
        self.session.add_user(content)
        turn = TurnState()
        task = asyncio.create_task(self._run_turn(turn, content, event))
        self._current = (task, turn)
        try:
            await task
        except asyncio.CancelledError:
            if self._interrupt_source is None:
                raise  # we are being shut down, not interrupted
            self._after_interrupt(turn)
        finally:
            self._current = None
            self._interrupt_source = None

    @property
    def busy(self) -> bool:
        """True while a turn (request, tools or speech) is in progress."""
        return self._current is not None

    def add_note(self, text: str) -> None:
        """Something Claude should know, sent with the next event (e.g. a card was closed)."""
        self._notes.append(text)

    def take_missed(self) -> tuple[Utterance, ...]:
        missed, self._missed = tuple(self._missed), []
        return missed

    def _take_notes(self) -> list[str]:
        notes, self._notes = self._notes, []
        return notes

    # ------------------------------------------------------------------ interruptions

    def interrupt(self, source: str) -> None:
        """Esc, the stop button or a barge-in: stop speaking and drop the request at once."""
        self.speech.stop()
        self.face.apply_preset("listening")
        if self._current is not None and not self._current[0].done():
            self._interrupt_source = source
            self._current[0].cancel()

    def _after_interrupt(self, turn: TurnState) -> None:
        heard = " ".join(r.spoken_text for r in turn.speech if r.spoken_text).strip()
        unheard = " ".join(r.unspoken_text for r in turn.speech if r.unspoken_text).strip()
        doing = "speaking" if turn.speech else "working on your reply"
        parts = [f"[Note: the person interrupted you with {self._interrupt_source} while you "
                 f"were {doing}."]
        parts.append(f'They heard: "{heard}".' if heard else "They heard nothing from you.")
        if unheard:
            parts.append(f'They did not hear: "{unheard}".')
        parts.append("Everything else you were doing in that turn was cancelled.]")
        self._notes.append(" ".join(parts))
        log.info("interrupted (%s)", self._interrupt_source)

    # ------------------------------------------------------------------ one turn

    def build_params(self) -> dict[str, Any]:
        return request_params(self.cfg, self.system_prompt, self.registry.api_definitions(),
                              self.session.window())

    async def _run_turn(self, turn: TurnState, event_content: list[dict[str, Any]],
                        event: Event) -> None:
        ctx = self.make_context(turn)
        ctx.conversation = self.conversation
        self.face.set_busy(True)
        self.face.apply_preset("waiting")
        try:
            for _ in range(self.cfg.max_tool_rounds):
                outcome = await self._round(ctx, event_content,
                                            asked=isinstance(event, Utterance))
                if outcome is None:
                    return
                message, executor = outcome
                self._record_usage(event, message)
                if message.stop_reason == "refusal":
                    log.warning("Claude declined (refusal): %s", getattr(
                        message, "stop_details", None))
                    executor.cancel()
                    return
                self.session.add_assistant(message.content)
                _log_text_blocks(message)
                tool_uses = [b for b in message.content if b.type == "tool_use"]
                if not tool_uses:
                    if message.stop_reason == "pause_turn":
                        continue  # a server tool paused; send the turn back to continue
                    return
                try:
                    results = await executor.results_for(tool_uses)
                except asyncio.CancelledError:
                    executor.cancel()
                    self.session.add_user(executor.finished_results(tool_uses))
                    raise
                self.session.add_user(results)
            log.warning("stopped after %d tool rounds", self.cfg.max_tool_rounds)
        except ClaudeFailure as failure:
            await self._report_failure(failure, event)
        finally:
            self.face.set_busy(False)
            if self.health.online and self._interrupt_source is None:
                self.face.schedule_preset("idle", self.idle_after_s)

    async def _round(self, ctx: ToolContext, event_content: list[dict[str, Any]],
                     asked: bool = True) -> tuple[Any, ToolExecutor] | None:
        """One request to Claude, with the design's retries. Tools run as they stream in.

        `asked`: someone spoke. Only then does cadbot say "One moment." while retrying.
        """
        started = time.monotonic()
        attempt, said_one_moment, restarted = 0, False, False
        while True:
            executor = ToolExecutor(self.registry, ctx)
            try:
                return await self._stream(executor), executor
            except asyncio.CancelledError:
                executor.cancel()
                raise
            except Exception as exc:
                executor.cancel()
                failure = classify(exc)
                log.warning("Claude request failed: %s", failure)
            if failure.kind in RETRYABLE and attempt < len(self.cfg.retry_delays_s):
                delay = min(MAX_RETRY_DELAY_S,
                            max(self.cfg.retry_delays_s[attempt], failure.retry_after_s or 0))
                attempt += 1
                waited = time.monotonic() - started + delay
                if asked and not said_one_moment and waited > self.cfg.one_moment_after_s:
                    said_one_moment = True
                    await self.canned.play("one_moment", rate_limited=False)
                await self.sleep(delay)
                continue
            if failure.kind == ErrorKind.TOO_LARGE and not restarted:
                log.warning("request too large: starting a fresh conversation")
                restarted = True
                self.session.reset()
                self.session.add_user(event_content)
                continue
            raise failure

    async def _stream(self, executor: ToolExecutor) -> Any:
        async with self.client.stream(**self.build_params()) as stream:
            async for event in stream:
                if event.type == "content_block_stop":
                    block = getattr(event, "content_block", None)
                    if block is not None and block.type == "tool_use":
                        executor.submit(block)
            return await stream.get_final_message()

    def _record_usage(self, event: Event, message: Any) -> None:
        if self.usage_log is None or getattr(message, "usage", None) is None:
            return
        if isinstance(event, Utterance):
            kind, snapshot = "speech", event.snapshot
        elif isinstance(event, Observation):
            kind, snapshot = "camera", event.snapshot
        else:
            kind, snapshot = "other", None
        with_image = snapshot is not None and snapshot.jpeg is not None
        cost = self.usage_log.record(kind, with_image, getattr(message, "model", self.cfg.model)
                                     or self.cfg.model, message.usage)
        log.debug("request cost about $%.4f (%s%s)", cost, kind, ", image" if with_image else "")

    # ------------------------------------------------------------------ failures

    async def _report_failure(self, failure: ClaudeFailure, event: Event) -> None:
        kind = failure.kind
        log.error("Claude failed: %s", failure)
        if kind in NEEDS_OWNER:
            await self.notifier.alert(f"cadbot can't use Claude ({kind}): {failure.detail}")
        key = CANNED_KEY.get(kind, "unknown")
        if kind in (ErrorKind.OFFLINE, ErrorKind.TIMEOUT):
            if isinstance(event, Utterance):
                self._missed.append(event)
            network_ok = await self.health.check_now()
            self.health.mark_offline()
            key = "claude_unreachable" if network_ok else "offline"
            self._offline_key = key
        if not isinstance(event, Utterance):
            return  # nobody asked anything (a camera frame): log and alert, don't speak
        if kind not in (ErrorKind.OFFLINE, ErrorKind.TIMEOUT):
            self.face.set("sad" if kind in NEEDS_OWNER else "confused", 0.6)
        await self.canned.play(key)


def _log_text_blocks(message: Any) -> None:
    for block in message.content:
        if block.type == "text" and block.text.strip():
            log.debug("Claude wrote text (not spoken): %s", block.text.strip())

