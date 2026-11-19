# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Runs Claude's tool calls in order, each as soon as its block has streamed in.

So `set_face` changes the face before the rest of the reply arrives, and speech starts
while Claude may still be generating.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from cadbot.agent.tools.registry import ToolContext, ToolRegistry, ToolResult, validate_input

log = logging.getLogger(__name__)

INTERRUPTED = "Interrupted by the person before this finished."


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, ctx: ToolContext) -> None:
        self.registry = registry
        self.ctx = ctx
        self._tasks: dict[str, asyncio.Task[ToolResult]] = {}
        self._names: dict[str, str] = {}
        self._last: asyncio.Task[ToolResult] | None = None

    def submit(self, block: Any) -> None:
        if block.id in self._tasks:
            return
        previous = self._last
        task = asyncio.create_task(self._run(block.name, block.input, previous))
        self._tasks[block.id] = task
        self._names[block.id] = block.name
        self._last = task

    async def _run(self, name: str, args: Any,
                   previous: asyncio.Task[ToolResult] | None) -> ToolResult:
        if previous is not None:  # keep Claude's order: set_face before speak
            await asyncio.wait({previous})  # doesn't raise the previous tool's errors
        tool = self.registry.get(name)
        if tool is None:
            return ToolResult(f"Unknown tool {name!r}.", is_error=True)
        problem = validate_input(tool.input_schema, args)
        if problem:
            return ToolResult(f"Invalid input for {name}: {problem}", is_error=True)
        try:
            result = await tool.handler(args, self.ctx)
        except asyncio.CancelledError:
            self.ctx.turn.cancelled_tools.append(name)
            raise
        except Exception as exc:
            log.exception("tool %s failed", name)
            return ToolResult(f"{name} failed: {type(exc).__name__}: {exc}", is_error=True)
        self.ctx.turn.completed_tools.append(name)
        return result

    async def results_for(self, tool_uses: list[Any]) -> list[dict[str, Any]]:
        for block in tool_uses:
            self.submit(block)  # no-op for blocks already started while streaming
        results = []
        for block in tool_uses:
            result = await self._tasks[block.id]
            results.append(_as_param(block.id, result))
        return results

    def finished_results(self, tool_uses: list[Any]) -> list[dict[str, Any]]:
        """Results so far, with every unfinished call marked as interrupted."""
        out = []
        for block in tool_uses:
            task = self._tasks.get(block.id)
            if task is not None and task.done() and not task.cancelled() \
                    and task.exception() is None:
                out.append(_as_param(block.id, task.result()))
            else:
                out.append(_as_param(block.id, ToolResult(INTERRUPTED, is_error=True)))
        return out

    def cancel(self) -> None:
        """Cancel unfinished calls. Tools with side effects that already started finish."""
        for tool_id, task in self._tasks.items():
            tool = self.registry.get(self._names[tool_id])
            if task.done() or (tool is not None and tool.side_effects):
                continue
            task.cancel()


def _as_param(tool_use_id: str, result: ToolResult) -> dict[str, Any]:
    param: dict[str, Any] = {"type": "tool_result", "tool_use_id": tool_use_id,
                             "content": result.content}
    if result.is_error:
        param["is_error"] = True
    return param
