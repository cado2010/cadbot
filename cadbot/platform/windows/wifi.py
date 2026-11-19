# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Wi-Fi scanning on Windows with `netsh wlan show networks mode=bssid`."""

from __future__ import annotations

import logging
import re
import subprocess

from cadbot.platform.base import WifiAP

log = logging.getLogger(__name__)

_SSID = re.compile(r"^\s*SSID \d+\s*:\s?(.*)$")
_BSSID = re.compile(r"^\s*BSSID \d+\s*:\s*([0-9A-Fa-f:]{17})\s*$")
_SIGNAL = re.compile(r"^\s*Signal\s*:\s*(\d+)%")


def signal_percent_to_dbm(percent: int) -> int:
    """Windows reports signal quality 0..100%; map it onto -100..-50 dBm."""
    return int(min(max(percent, 0), 100) / 2 - 100)


def parse_netsh(output: str) -> list[WifiAP]:
    aps: list[WifiAP] = []
    ssid, bssid = "", None
    for line in output.splitlines():
        if m := _SSID.match(line):
            ssid, bssid = m.group(1).strip(), None
        elif m := _BSSID.match(line):
            bssid = m.group(1).lower()
        elif (m := _SIGNAL.match(line)) and bssid:
            aps.append(WifiAP(bssid=bssid, rssi_dbm=signal_percent_to_dbm(int(m.group(1))),
                              ssid=ssid))
            bssid = None
    return aps


class NetshWifiScanner:
    def scan(self) -> list[WifiAP]:
        try:
            result = subprocess.run(["netsh", "wlan", "show", "networks", "mode=bssid"],
                                    capture_output=True, text=True, check=False, timeout=20)
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("Wi-Fi scan failed: %s", exc)
            return []
        aps = parse_netsh(result.stdout)
        if not aps and "location" in result.stdout.lower():
            log.warning("Windows blocked the Wi-Fi scan: allow location access for desktop "
                        "apps (Settings > Privacy & security > Location), or set the "
                        "location in config.yaml")
        return aps


def make_wifi() -> NetshWifiScanner:
    return NetshWifiScanner()
