# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Test setup: fake hardware by default, no real API key, headless SDL."""

from __future__ import annotations

import os

# Before anything imports cadbot or pygame.
os.environ.setdefault("CADBOT_PLATFORM", "fake")
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ.pop("ANTHROPIC_API_KEY", None)  # tests must never reach the real API

import pytest

from tests.fakes.harness import AgentHarness, make_harness


@pytest.fixture
def harness() -> AgentHarness:
    return make_harness()
