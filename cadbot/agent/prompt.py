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


CAMERA_NOTES = {
    "images": "",
    "readings": "- To save cost, camera images are not sent to you: you get only the face "
                "readings, as text, when someone appears and at your watch interval. Don't "
                "describe what you can't see; ask if it matters.",
    "none": "- To save cost, you get no camera events and no images. The face readings come "
            "only with what people say. Don't describe what you can't see; ask if it matters.",
    "off": "- The camera is switched off: you can't see anyone, and nobody is recognised.",
}


def build_system_prompt(capabilities: Capabilities, platform_name: str,
                        household_wishes: str = "", template: str | None = None,
                        camera: str = "images") -> str:
    """`camera`: vision.send_to_claude ("images", "readings", "none"), or "off"."""
    text = template if template is not None else load_template()
    device = {"windows": "a development PC (webcam, microphone and headphones)",
              "pi": "a Raspberry Pi 5 with a touchscreen",
              "fake": "a test machine with simulated hardware"}.get(platform_name, platform_name)
    caps = "\n".join(f"- It {line}." for line in capabilities.describe())
    if CAMERA_NOTES.get(camera):
        caps += "\n" + CAMERA_NOTES[camera]
    capabilities_block = f"You are running on {device}. This device:\n{caps}"
    household = household_wishes.strip()
    household_block = f"# This household\n\n{household}" if household else ""
    return (text.replace("{capabilities}", capabilities_block)
            .replace("{household}", household_block).strip() + "\n")
