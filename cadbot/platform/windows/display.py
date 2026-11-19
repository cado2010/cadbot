# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Windows display: a resizable 1280x720 pygame window; the mouse acts as touch."""

from __future__ import annotations

from cadbot.platform.common.pygame_display import PygameDisplay


def make_display() -> PygameDisplay:
    return PygameDisplay(fullscreen=False)
