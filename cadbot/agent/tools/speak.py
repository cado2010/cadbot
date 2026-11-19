# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""speak(text, lang): Piper speech. Replies longer than ~60 words go back to Claude to shorten."""

from __future__ import annotations

from typing import Any

from cadbot.actuators.speech import SpeechResult
from cadbot.agent.tools.registry import HelpInfo, Tool, ToolContext, ToolResult


def word_count(text: str) -> int:
    return len(text.split())


async def speak(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    text: str = args["text"].strip()
    lang: str = args.get("lang") or "en"
    limit = ctx.config.speak_max_words
    if not text:
        return ToolResult("Nothing to say: text was empty.", is_error=True)
    words = word_count(text)
    if words > limit:
        return ToolResult(
            f"Not spoken: too long for speech ({words} words; the limit is about {limit}). "
            "Shorten it to one to three short sentences, or say the gist and offer details.",
            is_error=True)
    available = ctx.speech.tts.languages()
    if lang not in available:
        return ToolResult(f"No voice for language {lang!r}; available: {', '.join(available)}.",
                          is_error=True)
    if not ctx.turn.face_set:
        ctx.face.apply_preset("speaking")
    result = SpeechResult()
    ctx.turn.speech.append(result)  # filled in live, so an interruption is reported exactly
    await ctx.speech.speak(text, lang, result)
    if result.interrupted:
        return ToolResult(
            f'Interrupted. The person heard: "{result.spoken_text}". '
            f'They did not hear: "{result.unspoken_text}".')
    return ToolResult("Spoken.")


TOOL = Tool(
    name="speak",
    description=(
        "Say something aloud through the speaker. This is the only way to talk to people. "
        "Use 1-3 short spoken sentences (about 60 words at most), no markdown, lists, URLs "
        "or emoji. Say numbers and times the way people say them. Returns 'Spoken.' or "
        "what the person actually heard if they interrupted."),
    input_schema={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "What to say, as plain speech."},
            "lang": {"type": "string",
                     "description": "Language code of the text, e.g. 'en'. Defaults to 'en'."},
        },
        "required": ["text"],
        "additionalProperties": False,
    },
    handler=speak,
    help=HelpInfo(
        category="Talking and questions",
        summary="Answer questions and chat, out loud",
        examples=("What's the capital of Peru?", "Tell me a joke"),
    ),
)
