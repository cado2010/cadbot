# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""No service manager on the PC: lifecycle notifications are no-ops."""

from __future__ import annotations


class NullLifecycle:
    def notify_ready(self) -> None:
        pass

    def watchdog_ping(self) -> None:
        pass

    def notify_stopping(self) -> None:
        pass
