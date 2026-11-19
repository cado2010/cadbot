# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""cadbot: a home assistant bot whose every decision is made by Claude."""

import os

__version__ = "0.1.0"

# pygame prints a banner on import; keep the console for cadbot's own logs.
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
