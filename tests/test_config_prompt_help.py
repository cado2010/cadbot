# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Config layering, the system prompt, the router and help built from the registry."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from cadbot.agent.prompt import build_system_prompt
from cadbot.agent.tools import build_registry
from cadbot.agent.tools.help import build_help
from cadbot.agent.tools.registry import HELP_CATEGORIES, ToolContext, validate_input
from cadbot.bus import Utterance
from cadbot.config import AgentConfig, load_config
from cadbot.platform.base import Capabilities
from cadbot.router import render_event, spoken_time

REPO = Path(__file__).resolve().parents[1]


def test_example_config_is_valid() -> None:
    for name in ("windows", "pi", "fake"):
        config = load_config(name, path=REPO / "config.example.yaml")
        assert config.agent.model == "claude-opus-5-5"


def test_platform_section_overrides(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("stt:\n  model: small.en\nplatforms:\n  pi:\n    stt:\n      model: base.en\n")
    assert load_config("pi", path=path).stt.model == "base.en"
    assert load_config("windows", path=path).stt.model == "small.en"


def test_unknown_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("agent:\n  modle: oops\n")
    with pytest.raises(ValidationError):
        load_config("fake", path=path)


def test_system_prompt() -> None:
    caps = Capabilities(echo_cancellation=False, night_vision=False, keyboard=True)
    prompt = build_system_prompt(caps, "windows", "Quiet hours are 10 pm to 7 am.")
    assert "Your name is cadbot" in prompt
    assert "cannot see in the dark" in prompt
    assert "mic is muted while you speak" in prompt
    assert "Quiet hours are 10 pm to 7 am." in prompt
    assert "{capabilities}" not in prompt and "{household}" not in prompt
    assert prompt == build_system_prompt(caps, "windows", "Quiet hours are 10 pm to 7 am.")


def test_router_formats_time_and_text() -> None:
    event = Utterance("hello cadbot", datetime(2026, 11, 19, 9, 5), 1.234, during_speech=True)
    text = render_event(event, ["[Note: x]"])[0]["text"]
    assert text.splitlines()[0] == "[Note: x]"
    assert "Thu 19 Nov 2026, 9:05 am" in text and "1.2 s, while you were speaking" in text
    assert spoken_time(datetime(2026, 1, 2, 15, 30)) == "Fri 02 Jan 2026, 3:30 pm"


def _ctx(caps: Capabilities) -> ToolContext:
    registry = build_registry(AgentConfig())
    return ToolContext(speech=None, face=None, capabilities=caps,  # type: ignore[arg-type]
                       config=AgentConfig(), registry=registry)


def test_every_tool_has_help_metadata() -> None:
    for tool in build_registry(AgentConfig()).all():
        assert tool.help.category in HELP_CATEGORIES, tool.name
        assert tool.help.summary and tool.help.examples, tool.name


def test_help_overview_and_topics() -> None:
    overview = build_help(_ctx(Capabilities(keyboard=True)))
    assert "Search and translate" in overview and "Esc key" in overview
    assert "set_face" not in overview  # internal tools aren't offered as features
    assert "web" in build_help(_ctx(Capabilities()), "search").lower()
    assert "Nothing about" in build_help(_ctx(Capabilities()), "teleport")


def test_help_follows_capabilities() -> None:
    assert "Esc key" not in build_help(_ctx(Capabilities(keyboard=False)))


def test_validate_input() -> None:
    schema = {"type": "object", "properties": {"n": {"type": "number", "minimum": 0},
                                               "e": {"type": "string", "enum": ["a"]}},
              "required": ["n"], "additionalProperties": False}
    assert validate_input(schema, {"n": 1, "e": "a"}) is None
    assert "missing" in str(validate_input(schema, {}))
    assert "must be one of" in str(validate_input(schema, {"n": 1, "e": "b"}))
    assert ">=" in str(validate_input(schema, {"n": -1}))
    assert "unknown field" in str(validate_input(schema, {"n": 1, "x": 2}))
    assert validate_input(schema, "nope") == "input must be an object"
