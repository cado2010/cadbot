# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""show_card / hide_card: text or a picture on the screen while the face waits in a corner."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urlsplit

import numpy as np
import pygame

from cadbot.agent.tools.registry import HelpInfo, Tool, ToolContext, ToolResult
from cadbot.face.card import Card
from cadbot.net.images import ImageError, decode_image, fetch_image


def _camera_picture(ctx: ToolContext) -> pygame.Surface | None:
    """The newest camera frame, mirrored like a selfie (how people expect to see themselves)."""
    frame = ctx.vision.reader.latest() if ctx.vision is not None else None
    if frame is None:
        return None
    rgb = np.ascontiguousarray(frame.image[:, ::-1, ::-1])
    h, w = rgb.shape[:2]
    return pygame.image.frombuffer(rgb.tobytes(), (w, h), "RGB").copy()


async def show_card(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    title = (args.get("title") or "").strip()
    text = (args.get("text") or "").strip()
    url = (args.get("image_url") or "").strip()
    camera = bool(args.get("camera_photo"))
    if not (text or url or camera):
        return ToolResult("Give text, an image_url or camera_photo=true.", is_error=True)
    if url and camera:
        return ToolResult("Show either a picture from the web or the camera, not both.",
                          is_error=True)
    image, caption = None, ""
    if camera:
        image = _camera_picture(ctx)
        if image is None:
            return ToolResult("The camera has no picture right now.", is_error=True)
        caption = "camera, just now"
    elif url:
        try:
            data = await fetch_image(url)
            image = await asyncio.to_thread(decode_image, data)
        except ImageError as exc:
            return ToolResult(f"Couldn't show that picture: {exc}.", is_error=True)
        caption = urlsplit(url).hostname or ""
    seconds = int(min(600, max(10, args.get("seconds") or ctx.config.card_seconds)))
    ctx.face.show_card(Card(title=title, text=text, image=image, caption=caption,
                            close_at=time.monotonic() + seconds))
    return ToolResult(
        f"Shown on the screen (your face is in the corner). It closes when they tap Done, "
        f"after {seconds} seconds, or when you call hide_card. Say a one-line summary aloud "
        "instead of reading it out.")


async def hide_card(_args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    if ctx.face.hide_card("claude"):
        return ToolResult("Closed; the full face is back.")
    return ToolResult("No card was showing.")


SHOW_CARD = Tool(
    name="show_card",
    description=(
        "Show text and/or a picture on the screen; your face shrinks into the corner until "
        "it's closed. Use it for anything better read than heard: recipes, lists, directions, "
        "long answers, or when someone asks to see something. text: plain lines, '- ' for "
        "bullets. image_url: a direct link to a .jpg/.png/.gif/.webp picture on the public "
        "web (find one with web_search or web_fetch). camera_photo: show what the camera "
        "sees right now ('how do I look?'). seconds: how long before it closes by itself "
        "(10-600)."),
    input_schema={"type": "object", "properties": {
        "title": {"type": "string"},
        "text": {"type": "string"},
        "image_url": {"type": "string"},
        "camera_photo": {"type": "boolean"},
        "seconds": {"type": "integer", "minimum": 10, "maximum": 600}},
        "additionalProperties": False},
    handler=show_card,
    help=HelpInfo("Talking and questions", "Show text and pictures on the screen",
                  ("Show me the recipe", "Show me a picture of a red panda",
                   "How do I look?")),
)

HIDE_CARD = Tool(
    name="hide_card",
    description="Close the card on the screen and bring the full face back, e.g. when they "
                "say 'OK', 'done' or 'close it'.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    handler=hide_card,
    help=HelpInfo("Talking and questions", "Close what's on the screen", ("OK, done",),
                  user_facing=False),
)
