# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Fake display: pygame offscreen (SDL dummy driver). Supports injected events and screenshots."""

from __future__ import annotations

from cadbot.platform.common.pygame_display import PygameDisplay


def make_display() -> PygameDisplay:
    return PygameDisplay(fullscreen=False, video_driver="dummy")
