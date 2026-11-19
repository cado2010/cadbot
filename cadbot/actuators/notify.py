# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Owner alerts for problems someone must fix (bad key, budget used up).

M1 logs them. A later milestone adds ntfy/Pushover behind the same interface, and a
`notify_phone` tool for Claude.
"""

from __future__ import annotations

import logging
from typing import Protocol

log = logging.getLogger(__name__)


class OwnerNotifier(Protocol):
    async def alert(self, text: str) -> None: ...


class LogNotifier:
    async def alert(self, text: str) -> None:
        log.error("OWNER ACTION NEEDED: %s", text)
