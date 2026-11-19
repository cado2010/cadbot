# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Windows system info via psutil. CPU temperature is usually not exposed (None)."""

from __future__ import annotations

import platform as pyplatform

import psutil


class WindowsSystemInfo:
    def cpu_temperature_c(self) -> float | None:
        return None

    def cpu_load(self) -> float:
        return float(psutil.cpu_percent(interval=None)) / 100.0

    def model_name(self) -> str:
        return f"Windows PC ({pyplatform.processor() or pyplatform.machine()})"
