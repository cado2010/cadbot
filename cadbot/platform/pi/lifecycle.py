# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""systemd notifications (READY=1, WATCHDOG=1) over NOTIFY_SOCKET, without extra packages.

UNTESTED: written before the Raspberry Pi hardware arrived.
"""

from __future__ import annotations

import logging
import os
import socket

log = logging.getLogger(__name__)


class SystemdLifecycle:
    def _notify(self, message: str) -> None:
        address = os.environ.get("NOTIFY_SOCKET")
        if not address:
            return
        if address.startswith("@"):
            address = "\0" + address[1:]
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
                sock.connect(address)
                sock.sendall(message.encode())
        except OSError as exc:
            log.warning("sd_notify failed: %s", exc)

    def notify_ready(self) -> None:
        self._notify("READY=1")

    def watchdog_ping(self) -> None:
        self._notify("WATCHDOG=1")

    def notify_stopping(self) -> None:
        self._notify("STOPPING=1")
