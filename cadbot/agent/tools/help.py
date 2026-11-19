# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""get_help(topic?): what cadbot can do right now, built from the tool registry.

Filtered by platform capabilities today; by who's asking, mode and connected accounts in
later milestones (HelpInfo.audience is already recorded for that).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from cadbot.agent.tools.registry import HELP_CATEGORIES, HelpInfo, Tool, ToolContext, ToolResult

# Abilities that need no tool: Claude answers from its own knowledge.
BUILT_IN: tuple[HelpInfo, ...] = (
    HelpInfo("Search and translate", "Translate words and phrases, and say them aloud",
             ("How do I say 'where is the station' in Spanish?",)),
    HelpInfo("cadbot itself", "Stop me any time with the Esc key or the stop button",
             ("Press Esc while I'm talking",), requires=("keyboard",)),
)


def _offered(info: HelpInfo, ctx: ToolContext) -> bool:
    return info.user_facing and all(getattr(ctx.capabilities, flag, False)
                                    for flag in info.requires)


def build_help(ctx: ToolContext, topic: str | None = None) -> str:
    entries: dict[str, list[HelpInfo]] = defaultdict(list)
    for item in [*(t.help for t in ctx.registry.all()), *BUILT_IN]:
        if _offered(item, ctx):
            entries[item.category].append(item)
    if topic:
        wanted = topic.lower()
        matches = [c for c in entries if wanted in c.lower()] or [
            c for c, items in entries.items()
            if any(wanted in i.summary.lower() for i in items)]
        if not matches:
            return (f"Nothing about {topic!r} yet. Available categories: "
                    + ", ".join(sorted(entries)) + ".")
        lines = []
        for category in matches:
            for item in entries[category]:
                lines.append(f"{category}: {item.summary}. Try: "
                             + "; ".join(f"'{e}'" for e in item.examples))
        return "\n".join(lines)
    ordered = [c for c in HELP_CATEGORIES if c in entries]
    lines = ["What cadbot can do right now (summarise in about 20 seconds of speech, then "
             "offer to go deeper; never read the whole list):"]
    for category in ordered:
        lines.append(f"- {category}: " + "; ".join(i.summary for i in entries[category]))
    lines.append("Not available yet: reminders, calendar, email, photos, saved conversations, "
                 "incognito and group mode. They arrive in later versions.")
    return "\n".join(lines)


async def get_help(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    return ToolResult(build_help(ctx, args.get("topic")))


TOOL = Tool(
    name="get_help",
    description=(
        "What cadbot can do right now, with example phrases. Call it when someone asks for "
        "help, 'what can you do?', or how to do something. Without a topic you get an "
        "overview; with a topic (e.g. 'search', 'privacy'), details and examples."),
    input_schema={
        "type": "object",
        "properties": {"topic": {"type": "string", "description": "Optional help topic."}},
        "additionalProperties": False,
    },
    handler=get_help,
    help=HelpInfo(category="cadbot itself", summary="Explain what I can do",
                  examples=("What can you do?", "How do I stop you?")),
)

WEB_SEARCH_HELP = HelpInfo(
    category="Search and translate", summary="Search the web for live facts and news",
    examples=("What's the weather this weekend?", "Who won the game last night?"))


def all_local_tools() -> list[Tool]:
    from cadbot.agent.tools import costs, face, location, people, speak, vision

    return [face.SET_FACE, speak.TOOL, face.SET_FACE_PRESETS, TOOL,
            vision.SET_WATCH_INTERVAL, vision.SET_LISTENING, vision.SET_GAZE, *people.ALL,
            costs.TOOL, location.TOOL]
