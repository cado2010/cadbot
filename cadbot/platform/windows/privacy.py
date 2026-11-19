# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Privacy switch on Windows: not implemented yet (key toggle plus on-screen indicator)."""

from __future__ import annotations

from cadbot.platform.base import PrivacySwitch, not_implemented


def make_privacy() -> PrivacySwitch:
    raise not_implemented("windows", "PrivacySwitch", "a later milestone")
