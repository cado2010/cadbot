# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Is Claude reachable? An HTTPS request to the API every 30 s; offline after two failures.

A failed Claude call marks it offline at once. Coming back online triggers a back_online
event so Claude can decide whether to mention what it missed.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from collections.abc import Awaitable, Callable
from datetime import datetime

import httpx
import truststore

log = logging.getLogger(__name__)

Probe = Callable[[], Awaitable[bool]]


def https_probe(url: str, timeout_s: float = 5.0) -> Probe:
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    async def probe() -> bool:
        try:
            async with httpx.AsyncClient(verify=context, timeout=timeout_s) as client:
                await client.head(url)  # any HTTP answer means the network path works
            return True
        except httpx.HTTPError as exc:
            log.debug("health probe failed: %s", type(exc).__name__)
            return False

    return probe


class HealthMonitor:
    def __init__(self, probe: Probe, *, interval_s: float = 30.0,
                 failures_before_offline: int = 2,
                 on_change: Callable[[bool, datetime], None] = lambda _online, _since: None,
                 ) -> None:
        self.probe = probe
        self.interval_s = interval_s
        self.failures_before_offline = failures_before_offline
        self.on_change = on_change
        self.online = True
        self.offline_since: datetime | None = None
        self._failures = 0

    def mark_offline(self) -> None:
        if self.online:
            self.online = False
            self.offline_since = datetime.now()
            log.warning("Claude unreachable: offline")
            self.on_change(False, self.offline_since)

    def _record(self, ok: bool) -> None:
        if ok:
            self._failures = 0
            if not self.online:
                since = self.offline_since or datetime.now()
                self.online = True
                self.offline_since = None
                log.info("Claude reachable again")
                self.on_change(True, since)
            return
        self._failures += 1
        if self._failures >= self.failures_before_offline:
            self.mark_offline()

    async def check_now(self) -> bool:
        """Probe once; returns whether the network path to the API works right now."""
        ok = await self.probe()
        self._record(ok)
        return ok

    async def run(self) -> None:
        while True:
            # check more often while offline, so recovery is noticed quickly
            await asyncio.sleep(self.interval_s if self.online else min(10.0, self.interval_s))
            await self.check_now()
