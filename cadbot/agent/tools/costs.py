# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""get_costs: what cadbot has spent on the Claude API (local estimate)."""

from __future__ import annotations

from typing import Any

from cadbot.agent.tools.registry import HelpInfo, Tool, ToolContext, ToolResult
from cadbot.usage import summary_text


async def get_costs(_args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    if ctx.usage is None:
        return ToolResult("Spending isn't being recorded right now.", is_error=True)
    return ToolResult(summary_text(ctx.usage) + "\nSay it briefly, e.g. 'About forty cents "
                      "today, most of it from the camera.' The billed amount is on the "
                      "Usage page of the Claude Console.")


TOOL = Tool(
    name="get_costs",
    description=(
        "What cadbot has spent on the Claude API today, in the last 7 days and this month, "
        "split into talking and camera frames. An estimate from token counts. Share it with "
        "household members who ask, not with visitors."),
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    handler=get_costs,
    help=HelpInfo("cadbot itself", "Tell you what I've cost to run",
                  ("How much have you spent today?",), audience="household"),
)
