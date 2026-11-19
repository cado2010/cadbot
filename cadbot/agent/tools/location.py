# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""get_location: where the device is, from the cached location record."""

from __future__ import annotations

from typing import Any

from cadbot.agent.tools.registry import HelpInfo, Tool, ToolContext, ToolResult


async def get_location(_args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    loc = ctx.location.current if ctx.location is not None else None
    if loc is None:
        return ToolResult("The location isn't known yet.", is_error=True)
    how = {"manual": "set by the owner", "wifi": "from nearby Wi-Fi networks",
           "ip": "from the internet connection (city level at best)"}.get(loc.source, loc.source)
    accuracy = f"about {loc.accuracy_m:.0f} m" if loc.accuracy_m else "unknown"
    lines = [
        f"Place: {loc.label}" + (f", {loc.country}" if loc.country else ""),
        f"Address: {loc.address or 'unknown'}",
        f"Coordinates: {loc.lat:.5f}, {loc.lon:.5f} (accuracy {accuracy}, {how})",
        f"Timezone: {loc.timezone or 'unknown'}",
        f"Updated: {loc.updated_at}",
        "Never say the street address to people you don't know or in front of a group; "
        "share it only with household members who ask.",
    ]
    return ToolResult("\n".join(lines))


TOOL = Tool(
    name="get_location",
    description=(
        "The device's full location record: address, coordinates, accuracy, timezone and how "
        "it was found. Every event already says the city; call this when you need more, e.g. "
        "an exact address for directions."),
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    handler=get_location,
    help=HelpInfo("Around you", "Know where we are, for weather and 'near me' questions",
                  ("What's the weather here?", "Where's the nearest pharmacy?")),
)
