# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Presence sensor on Windows: not implemented yet (key toggle or LD2410C on a COM port)."""

from __future__ import annotations

from cadbot.platform.base import PresenceSensor, not_implemented


def make_presence() -> PresenceSensor:
    raise not_implemented("windows", "PresenceSensor", "a later milestone")
