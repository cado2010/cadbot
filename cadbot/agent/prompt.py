# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Builds the system prompt once at startup. It must stay byte-stable for prompt caching,
so nothing volatile (like the time) goes in it; the time travels with each event instead.
"""

from __future__ import annotations

from importlib import resources

from cadbot.platform.base import Capabilities


def load_template() -> str:
    return resources.files("cadbot.prompts").joinpath("system.md").read_text(encoding="utf-8")


def build_system_prompt(capabilities: Capabilities, platform_name: str,
                        household_wishes: str = "", template: str | None = None) -> str:
    text = template if template is not None else load_template()
    device = {"windows": "a development PC (webcam, microphone and headphones)",
              "pi": "a Raspberry Pi 5 with a touchscreen",
              "fake": "a test machine with simulated hardware"}.get(platform_name, platform_name)
    caps = "\n".join(f"- It {line}." for line in capabilities.describe())
    capabilities_block = f"You are running on {device}. This device:\n{caps}"
    household = household_wishes.strip()
    household_block = f"# This household\n\n{household}" if household else ""
    return (text.replace("{capabilities}", capabilities_block)
            .replace("{household}", household_block).strip() + "\n")
