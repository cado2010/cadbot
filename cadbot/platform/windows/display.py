# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Windows display: a resizable portrait window showing the Pi's 720x1280 screen scaled down
(450x800 by default); the mouse acts as touch."""

from __future__ import annotations

from cadbot.platform.common.pygame_display import PygameDisplay

DEFAULT_WINDOW = (450, 800)


def make_display(window_size: tuple[int, int] | None = None) -> PygameDisplay:
    return PygameDisplay(fullscreen=False, window_size=window_size or DEFAULT_WINDOW)
