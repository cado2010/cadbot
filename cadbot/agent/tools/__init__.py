# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""The tool registry for M1: speak, set_face, set_face_presets, get_help and web_search.

Later milestones register more tools here (one module each); nothing else changes.
"""

from __future__ import annotations

from cadbot.agent.tools.help import WEB_FETCH_HELP, WEB_SEARCH_HELP, all_local_tools
from cadbot.agent.tools.registry import ServerTool, ToolRegistry
from cadbot.config import AgentConfig


def build_registry(config: AgentConfig,
                   user_location: dict[str, str] | None = None) -> ToolRegistry:
    """`user_location` (approximate city/region/country/timezone) makes web searches local.
    Tools stay fixed for the session, so it's taken once, at startup."""
    registry = ToolRegistry()
    for tool in all_local_tools():
        registry.register(tool)
    search: dict[str, object] = {"type": "web_search_20260209", "name": "web_search",
                                 "max_uses": config.web_search_max_uses}
    if user_location:
        search["user_location"] = user_location
    registry.register_server(ServerTool(search, WEB_SEARCH_HELP))
    registry.register_server(ServerTool(
        {"type": "web_fetch_20260209", "name": "web_fetch",
         "max_uses": config.web_fetch_max_uses}, WEB_FETCH_HELP))
    return registry
