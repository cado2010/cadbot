# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""set_face and set_face_presets: Claude chooses every expression; the Pi animates it."""

from __future__ import annotations

from typing import Any

from cadbot.agent.tools.registry import HelpInfo, Tool, ToolContext, ToolResult
from cadbot.face.expressions import EXPRESSIONS, LOOKS, PRESET_MOMENTS

_EXPRESSION_NAMES = list(EXPRESSIONS)


async def set_face(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    ctx.face.set(args["expression"], float(args.get("intensity", 1.0)), args.get("look"))
    ctx.turn.face_set = True
    return ToolResult("ok")


async def set_face_presets(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    presets = {moment: args[moment] for moment in PRESET_MOMENTS if moment in args}
    if not presets:
        return ToolResult("Give at least one of: " + ", ".join(PRESET_MOMENTS), is_error=True)
    ctx.face.set_presets(presets)
    return ToolResult("Presets saved: " + ", ".join(f"{k}={v}" for k, v in presets.items()))


SET_FACE = Tool(
    name="set_face",
    description=(
        "Change the expression on cadbot's face screen. Call it first in a turn, before "
        "speaking, so the face matches what you're about to say. Expressions: "
        + ", ".join(_EXPRESSION_NAMES) + ". Use 'empathetic' when someone is sad, 'calm' when "
        "someone is angry (never mirror anger), 'curious' while searching. Keep intensity "
        "modest (0.4-0.7) when someone is upset."),
    input_schema={
        "type": "object",
        "properties": {
            "expression": {"type": "string", "enum": _EXPRESSION_NAMES},
            "intensity": {"type": "number", "minimum": 0, "maximum": 1,
                          "description": "0-1, how strong the expression is. Default 1."},
            "look": {"type": "string", "enum": list(LOOKS),
                     "description": "Where the eyes look. Default: the expression's own."},
        },
        "required": ["expression"],
        "additionalProperties": False,
    },
    handler=set_face,
    help=HelpInfo(category="cadbot itself", summary="Shows how cadbot feels on its face",
                  examples=("Make a happy face",), user_facing=False),
)

SET_FACE_PRESETS = Tool(
    name="set_face_presets",
    description=(
        "Choose the expressions the device shows on its own at moments before you're asked: "
        "listening (someone starts talking), waiting (a request has gone out to you), "
        "speaking (while talking, if you didn't call set_face this turn) and idle (after a "
        "turn ends). Moments you leave out keep their current preset."),
    input_schema={
        "type": "object",
        "properties": {
            moment: {"type": "string", "enum": _EXPRESSION_NAMES} for moment in PRESET_MOMENTS
        },
        "additionalProperties": False,
    },
    handler=set_face_presets,
    help=HelpInfo(category="cadbot itself", summary="Sets cadbot's default faces",
                  examples=("Look sleepy when you're idle",), user_facing=False),
)
