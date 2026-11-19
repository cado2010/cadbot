# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Offline detection: two failed checks in a row, recovery notifies once."""

from __future__ import annotations

from datetime import datetime

from cadbot.net.health import HealthMonitor


async def test_offline_after_two_failures_then_back() -> None:
    results = [False, False, True]
    changes: list[tuple[bool, datetime]] = []

    async def probe() -> bool:
        return results.pop(0)

    health = HealthMonitor(probe, failures_before_offline=2,
                           on_change=lambda online, since: changes.append((online, since)))
    await health.check_now()
    assert health.online and changes == []
    await health.check_now()
    assert not health.online and changes[0][0] is False
    await health.check_now()
    assert health.online and changes[1][0] is True
    assert changes[1][1] == changes[0][1]  # "since" is when it went offline


async def test_failed_api_call_marks_offline_immediately() -> None:
    async def probe() -> bool:
        return True

    changes: list[bool] = []
    health = HealthMonitor(probe, on_change=lambda online, _since: changes.append(online))
    health.mark_offline()
    health.mark_offline()
    assert changes == [False]
