# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Wi-Fi scanning on Windows: not implemented yet (netsh wlan show networks mode=bssid)."""

from __future__ import annotations

from cadbot.platform.base import WifiScanner, not_implemented


def make_wifi() -> WifiScanner:
    raise not_implemented("windows", "WifiScanner", "the location milestone")
