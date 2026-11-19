# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Wi-Fi scan with nmcli (works while connected).

UNTESTED on hardware. The output parser is unit-tested.
"""

from __future__ import annotations

import re
import subprocess

from cadbot.platform.base import WifiAP

_UNESCAPED_COLON = re.compile(r"(?<!\\):")


def signal_percent_to_dbm(percent: int) -> int:
    """NetworkManager reports 0..100; map linearly onto -100..-50 dBm."""
    return int(min(max(percent, 0), 100) / 2 - 100)


def parse_nmcli(output: str) -> list[WifiAP]:
    """Parse `nmcli -t -f BSSID,SIGNAL,SSID dev wifi list` (colons in values are escaped)."""
    aps: list[WifiAP] = []
    for line in output.splitlines():
        fields = [f.replace("\\:", ":") for f in _UNESCAPED_COLON.split(line.strip())]
        if len(fields) < 3 or not fields[1].isdigit():
            continue
        bssid, signal, ssid = fields[0], int(fields[1]), ":".join(fields[2:])
        aps.append(WifiAP(bssid=bssid.lower(), rssi_dbm=signal_percent_to_dbm(signal), ssid=ssid))
    return aps


class NmcliWifiScanner:
    def scan(self) -> list[WifiAP]:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "BSSID,SIGNAL,SSID", "dev", "wifi", "list"],
            capture_output=True, text=True, check=False, timeout=20,
        )
        return parse_nmcli(result.stdout) if result.returncode == 0 else []


def make_wifi() -> NmcliWifiScanner:
    return NmcliWifiScanner()
