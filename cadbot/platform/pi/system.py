# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Pi system info from /sys and /proc.

UNTESTED: written before the Raspberry Pi hardware arrived.
"""

from __future__ import annotations

import os
from pathlib import Path

THERMAL = Path("/sys/class/thermal/thermal_zone0/temp")
MODEL = Path("/proc/device-tree/model")


class PiSystemInfo:
    def cpu_temperature_c(self) -> float | None:
        try:
            return int(THERMAL.read_text().strip()) / 1000.0
        except (OSError, ValueError):
            return None

    def cpu_load(self) -> float:
        return os.getloadavg()[0] / (os.cpu_count() or 1)

    def model_name(self) -> str:
        try:
            return MODEL.read_text(errors="ignore").strip("\x00\n ")
        except OSError:
            return "Raspberry Pi"
