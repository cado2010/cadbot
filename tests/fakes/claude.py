# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""A scripted stand-in for the Claude API: no network, no key."""

from __future__ import annotations

import asyncio
import copy
import itertools
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

_ids = itertools.count(1)


@dataclass
class Block:
    type: str
    id: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None
    text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def tool_use(name: str, **args: Any) -> Block:
    return Block("tool_use", id=f"toolu_{next(_ids):04d}", name=name, input=args)


def text(value: str) -> Block:
    return Block("text", text=value)


@dataclass
class Message:
    content: list[Block]
    stop_reason: str = "end_turn"
    stop_details: Any = None
    usage: Any = field(default_factory=lambda: SimpleNamespace(
        input_tokens=10, output_tokens=5, cache_read_input_tokens=0))


def reply(*blocks: Block, stop_reason: str | None = None) -> Message:
    has_tools = any(b.type == "tool_use" for b in blocks)
    return Message(list(blocks), stop_reason or ("tool_use" if has_tools else "end_turn"))


@dataclass
class Slow:
    """Script entry: wait `delay` seconds before streaming `message`."""

    message: Message
    delay: float


class FakeStream:
    def __init__(self, message: Message, delay: float = 0.0) -> None:
        self.message = message
        self.delay = delay

    async def __aiter__(self) -> AsyncIterator[Any]:
        await asyncio.sleep(self.delay)
        for block in self.message.content:
            yield SimpleNamespace(type="content_block_start", content_block=block)
            await asyncio.sleep(0)
            yield SimpleNamespace(type="content_block_stop", content_block=block)

    async def get_final_message(self) -> Message:
        return self.message


class FakeClaudeClient:
    """Returns scripted messages (or raises scripted exceptions) in order."""

    def __init__(self, script: list[Message | Slow | BaseException] | None = None) -> None:
        self.script = list(script or [])
        self.requests: list[dict[str, Any]] = []

    @asynccontextmanager
    async def stream(self, **params: Any) -> AsyncIterator[FakeStream]:
        self.requests.append(copy.deepcopy(params))
        if not self.script:
            raise AssertionError("FakeClaudeClient: script exhausted")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, Slow):
            yield FakeStream(item.message, item.delay)
        else:
            yield FakeStream(item)
