# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Pi display: Touch Display 2, full screen. kmsdrm when there is no desktop session.

UNTESTED: written before the Raspberry Pi hardware arrived. Verify with `pytest -m hardware`.
"""

from __future__ import annotations

import os

from cadbot.platform.common.pygame_display import PygameDisplay


def make_display() -> PygameDisplay:
    has_desktop = bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))
    return PygameDisplay(fullscreen=True, video_driver=None if has_desktop else "kmsdrm",
                         hide_cursor=True)
