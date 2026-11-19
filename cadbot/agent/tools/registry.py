# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Tools Claude can call. Every tool carries help metadata, so get_help never drifts.

A tool only executes; the decision to call it is always Claude's.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from cadbot.actuators.speech import SpeechOutput, SpeechResult
    from cadbot.config import AgentConfig
    from cadbot.face.renderer import Face
    from cadbot.people.registry import PeopleRegistry
    from cadbot.platform.base import Capabilities
    from cadbot.sensors.listener import Listener
    from cadbot.usage import UsageLog
    from cadbot.vision.loop import VisionLoop

HELP_CATEGORIES = (
    "Talking and questions", "Search and translate", "Reminders and timers",
    "Calendar and email", "Photos", "People and memory", "Privacy", "Around you",
    "Web accounts", "cadbot itself",
)

Audience = Literal["everyone", "household", "admin"]


@dataclass(frozen=True)
class HelpInfo:
    category: str
    summary: str
    examples: tuple[str, ...]
    audience: Audience = "everyone"
    requires: tuple[str, ...] = ()
    """Capability flags (see Capabilities) that must be on for this to be offered."""
    user_facing: bool = True
    """False for tools only Claude uses internally (e.g. set_face): kept out of spoken help."""


@dataclass
class TurnState:
    """What happened during one turn; used to report interruptions honestly."""

    face_set: bool = False
    speech: list[SpeechResult] = field(default_factory=list)
    completed_tools: list[str] = field(default_factory=list)
    cancelled_tools: list[str] = field(default_factory=list)


@dataclass
class ConversationState:
    """Shared across turns: lets tools tell one utterance from the next (for confirmations)."""

    utterance_seq: int = 0
    last_utterance: str = ""
    confirmations: dict[str, tuple[str, int, float]] = field(default_factory=dict)
    """token -> (person_id, utterance_seq when issued, monotonic time issued)."""


@dataclass
class ToolContext:
    speech: SpeechOutput
    face: Face
    capabilities: Capabilities
    config: AgentConfig
    registry: ToolRegistry
    turn: TurnState = field(default_factory=TurnState)
    vision: VisionLoop | None = None
    people: PeopleRegistry | None = None
    listener: Listener | None = None
    conversation: ConversationState = field(default_factory=ConversationState)
    usage: UsageLog | None = None


@dataclass(frozen=True)
class ToolResult:
    content: str
    is_error: bool = False


Handler = Callable[[dict[str, Any], ToolContext], Awaitable[ToolResult]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Handler
    help: HelpInfo
    side_effects: bool = False
    """True if interrupting it half-way could leave something half-done: it then finishes."""

    def definition(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "input_schema": self.input_schema}


@dataclass(frozen=True)
class ServerTool:
    """A tool Anthropic runs (web search). Listed for help; no local handler."""

    definition_: dict[str, Any]
    help: HelpInfo

    @property
    def name(self) -> str:
        return str(self.definition_["name"])

    def definition(self) -> dict[str, Any]:
        return dict(self.definition_)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._server: dict[str, ServerTool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools or tool.name in self._server:
            raise ValueError(f"tool {tool.name!r} registered twice")
        self._tools[tool.name] = tool

    def register_server(self, tool: ServerTool) -> None:
        if tool.name in self._tools or tool.name in self._server:
            raise ValueError(f"tool {tool.name!r} registered twice")
        self._server[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool | ServerTool]:
        return [*self._tools.values(), *self._server.values()]

    def api_definitions(self) -> list[dict[str, Any]]:
        """Deterministic order (registration order), so the prompt cache stays valid."""
        return [t.definition() for t in self.all()]


def validate_input(schema: dict[str, Any], args: Any) -> str | None:
    """Minimal check of Claude's tool input against our (flat) schemas. None = valid."""
    if not isinstance(args, dict):
        return "input must be an object"
    props: dict[str, Any] = schema.get("properties", {})
    for name in schema.get("required", []):
        if name not in args:
            return f"missing required field {name!r}"
    types = {"string": str, "number": (int, float), "integer": int, "boolean": bool,
             "object": dict}
    for name, value in args.items():
        spec = props.get(name)
        if spec is None:
            if schema.get("additionalProperties") is False:
                return f"unknown field {name!r}"
            continue
        if value is None and not spec.get("required"):
            continue
        expected = types.get(spec.get("type", ""))
        if expected is not None and not isinstance(value, expected):
            return f"field {name!r} must be {spec['type']}"
        if "enum" in spec and value not in spec["enum"]:
            return f"field {name!r} must be one of {spec['enum']}"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in spec and value < spec["minimum"]:
                return f"field {name!r} must be >= {spec['minimum']}"
            if "maximum" in spec and value > spec["maximum"]:
                return f"field {name!r} must be <= {spec['maximum']}"
    return None
