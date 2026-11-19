# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Tools for how cadbot watches and listens: Claude sets its own pace."""

from __future__ import annotations

from typing import Any

from cadbot.agent.tools.registry import HelpInfo, Tool, ToolContext, ToolResult

NO_CAMERA = ToolResult("The camera isn't available right now.", is_error=True)


async def set_watch_interval(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    if ctx.vision is None:
        return NO_CAMERA
    used = ctx.vision.set_watch_interval(float(args["seconds"]))
    return ToolResult(f"You'll get a frame at least every {used:.0f} seconds, and sooner "
                      "whenever the scene changes or a new face appears.")


async def set_listening(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    if ctx.listener is None:
        return ToolResult("Listening can't be changed right now.", is_error=True)
    ctx.listener.enabled = bool(args["on"])
    if ctx.listener.enabled:
        return ToolResult("Listening again.")
    return ToolResult("The microphone is off. Speech won't reach you until you turn it back "
                      "on; plan when to do that (for example after the next observation).")


async def set_gaze(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    if ctx.vision is None:
        return NO_CAMERA
    target = str(args["target"]).strip().lower()
    if target.startswith("track"):
        number = target.removeprefix("track").strip()
        if not number.isdigit() or ctx.vision.tracker.get(int(number)) is None:
            return ToolResult(f"No {target!r} in view.", is_error=True)
        target = f"track {int(number)}"
    elif target not in ("auto", "off"):
        return ToolResult("target must be 'auto', 'off' or 'track <n>'.", is_error=True)
    ctx.vision.gaze_mode = target
    return ToolResult(f"Eyes: {target}.")


SET_WATCH_INTERVAL = Tool(
    name="set_watch_interval",
    description=(
        "How often you get a camera frame when nothing changes (a heartbeat), in seconds "
        "(10-3600). You also get a frame whenever the scene changes or a new face appears, at "
        "most every 10 seconds. Use a long interval for an empty or quiet room, a shorter one "
        "when you're waiting for someone."),
    input_schema={"type": "object", "properties": {
        "seconds": {"type": "number", "minimum": 10, "maximum": 3600}},
        "required": ["seconds"], "additionalProperties": False},
    handler=set_watch_interval,
    help=HelpInfo("cadbot itself", "Watches the room and notices people",
                  ("Keep an eye out for Sam",), requires=("camera",), user_facing=False),
)

SET_LISTENING = Tool(
    name="set_listening",
    description=(
        "Turn the microphone off or on, e.g. off while people in the room are clearly on a "
        "phone call, and back on afterwards."),
    input_schema={"type": "object", "properties": {"on": {"type": "boolean"}},
                  "required": ["on"], "additionalProperties": False},
    handler=set_listening,
    help=HelpInfo("Privacy", "Stop listening for a while",
                  ("Stop listening until I come back",)),
)

SET_GAZE = Tool(
    name="set_gaze",
    description=(
        "Whom your eyes follow on screen: 'auto' (the nearest face, the default), "
        "'track <n>' (that person, e.g. whoever is talking to you) or 'off'. Only a direction "
        "on screen; nothing is stored."),
    input_schema={"type": "object", "properties": {"target": {"type": "string"}},
                  "required": ["target"], "additionalProperties": False},
    handler=set_gaze,
    help=HelpInfo("cadbot itself", "My eyes follow whoever I'm talking to",
                  ("Look at me",), requires=("camera",)),
)
