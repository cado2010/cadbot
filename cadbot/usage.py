# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""What cadbot spends on the Claude API, recorded locally for every request.

Each request's token usage is stored with what triggered it (someone speaking, a camera
frame, or something else) and an estimated cost from the configured prices. It's real-time
but an estimate; `python -m cadbot.admin spend` can also ask Anthropic for the billed amount.
No personal data: only counts, times and the kind of event.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cadbot.config import PricingConfig

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_usage (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    at                    TEXT NOT NULL,
    kind                  TEXT NOT NULL,
    with_image            INTEGER NOT NULL,
    model                 TEXT NOT NULL,
    input_tokens          INTEGER NOT NULL,
    cache_write_tokens    INTEGER NOT NULL,
    cache_read_tokens     INTEGER NOT NULL,
    output_tokens         INTEGER NOT NULL,
    web_searches          INTEGER NOT NULL,
    cost_usd              REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS api_usage_at ON api_usage(at);
"""

KINDS = {"speech": "Talking (things people said)", "camera": "Camera frames (observations)",
         "other": "Other (back online, etc.)"}


@dataclass(frozen=True)
class Tokens:
    input: int = 0
    cache_write: int = 0
    cache_read: int = 0
    output: int = 0
    web_searches: int = 0

    def cost(self, prices: PricingConfig) -> float:
        per_million = (self.input * prices.input_per_mtok
                       + self.cache_write * prices.cache_write_per_mtok
                       + self.cache_read * prices.cache_read_per_mtok
                       + self.output * prices.output_per_mtok)
        return per_million / 1_000_000 + self.web_searches * prices.web_search_per_1k / 1000


def tokens_from_usage(usage: Any) -> Tokens:
    """Sum a response's usage, including compaction (reported outside the top-level fields)."""
    def get(obj: Any, name: str) -> int:
        return int(getattr(obj, name, 0) or 0)

    t = Tokens(get(usage, "input_tokens"), get(usage, "cache_creation_input_tokens"),
               get(usage, "cache_read_input_tokens"), get(usage, "output_tokens"),
               get(getattr(usage, "server_tool_use", None), "web_search_requests"))
    for item in getattr(usage, "iterations", None) or []:
        if getattr(item, "type", "") == "compaction":
            t = Tokens(t.input + get(item, "input_tokens"),
                       t.cache_write + get(item, "cache_creation_input_tokens"),
                       t.cache_read + get(item, "cache_read_input_tokens"),
                       t.output + get(item, "output_tokens"), t.web_searches)
    return t


@dataclass(frozen=True)
class KindTotal:
    kind: str
    requests: int
    images: int
    tokens: Tokens
    cost_usd: float


class UsageLog:
    def __init__(self, db_path: Path, prices: PricingConfig) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.prices = prices
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def record(self, kind: str, with_image: bool, model: str, usage: Any,
               at: datetime | None = None) -> float:
        """Store one request's usage; returns its estimated cost in USD."""
        tokens = tokens_from_usage(usage)
        cost = tokens.cost(self.prices)
        when = (at or datetime.now(UTC)).isoformat(timespec="seconds")
        try:
            with self._lock:
                self._db.execute(
                    "INSERT INTO api_usage (at, kind, with_image, model, input_tokens, "
                    "cache_write_tokens, cache_read_tokens, output_tokens, web_searches, "
                    "cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (when, kind, int(with_image), model, tokens.input, tokens.cache_write,
                     tokens.cache_read, tokens.output, tokens.web_searches, cost))
        except sqlite3.Error as exc:  # never let bookkeeping break a conversation
            log.warning("could not record API usage: %s", exc)
        return cost

    def totals(self, since: datetime) -> list[KindTotal]:
        with self._lock:
            rows = self._db.execute(
                "SELECT kind, COUNT(*), SUM(with_image), SUM(input_tokens), "
                "SUM(cache_write_tokens), SUM(cache_read_tokens), SUM(output_tokens), "
                "SUM(web_searches), SUM(cost_usd) FROM api_usage WHERE at >= ? "
                "GROUP BY kind ORDER BY kind",
                (since.astimezone(UTC).isoformat(timespec="seconds"),)).fetchall()
        return [KindTotal(kind, n, int(images or 0), Tokens(*(int(v or 0) for v in t)),
                          float(cost or 0)) for kind, n, images, *t, cost in rows]


def period_starts(now: datetime | None = None) -> dict[str, datetime]:
    """Local-time period boundaries: today, the last 7 days, this calendar month."""
    now = (now or datetime.now()).astimezone()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return {"today": midnight, "last 7 days": midnight - timedelta(days=6),
            "this month": midnight.replace(day=1)}


def summary_text(log_: UsageLog, now: datetime | None = None) -> str:
    """A short plain-text summary, by period and by what triggered the requests."""
    lines = []
    for label, since in period_starts(now).items():
        totals = log_.totals(since)
        total = sum(t.cost_usd for t in totals)
        parts = ", ".join(f"{t.kind} ${t.cost_usd:.2f} ({t.requests} requests"
                          + (f", {t.images} with images" if t.images else "") + ")"
                          for t in totals)
        lines.append(f"{label}: about ${total:.2f}" + (f": {parts}" if parts else ""))
    lines.append("Estimated from token counts at the configured prices; face recognition "
                 "runs on this device and costs nothing.")
    return "\n".join(lines)
