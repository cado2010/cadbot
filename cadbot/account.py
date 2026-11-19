# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Billed costs from the Anthropic account (Usage and Cost Analytics API, beta).

Needs an Admin API key (sk-ant-admin..., ANTHROPIC_ADMIN_KEY in .env). It is used only by the
owner's `python -m cadbot.admin spend` command, never by the running assistant. Anthropic's
figures lag by a few hours; cadbot's own log (cadbot/usage.py) is real-time but estimated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import anthropic


@dataclass
class BilledCost:
    since: datetime
    until: datetime
    key_id: str | None
    key_name: str | None
    cadbot_usd: float | None
    """Spent through cadbot's API key; None if the key couldn't be identified."""
    organization_usd: float
    by_model: dict[str, float] = field(default_factory=dict)


def hint_matches(hint: str | None, key: str) -> bool:
    """Does a Console key hint (e.g. 'sk-ant-api03-R2D...igAA') fit this key?"""
    if not hint:
        return False
    for sep in ("...", "…"):
        if sep in hint:
            prefix, _, suffix = hint.partition(sep)
            return key.startswith(prefix) and key.endswith(suffix)
    return False


def admin_client(admin_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=admin_key, max_retries=2, timeout=30)


def find_key(client: anthropic.Anthropic, api_key: str) -> tuple[str, str] | None:
    """The (id, name) of the Console API key cadbot uses, matched by its hint."""
    for key in client.beta.organization.api_keys.list(limit=100):
        if hint_matches(key.partial_key_hint, api_key):
            return key.id, key.name
    return None


def _usd(cents: str) -> float:
    return float(cents) / 100


def billed_cost(client: anthropic.Anthropic, since: datetime, until: datetime | None = None,
                key_id: str | None = None, key_name: str | None = None) -> BilledCost:
    """Cost for the organization and for cadbot's key between two times (max 31 days)."""
    until = until or datetime.now(UTC)
    if until - since > timedelta(days=31):
        raise ValueError("the account API covers at most 31 days per request")
    rows: list[Any] = list(client.beta.organization.analytics.cost.list(
        starting_at=since, ending_at=until, group_by=["api_key_id", "model"], limit=1000))
    organization = sum(_usd(r.cost.amount) for r in rows)
    cadbot = None
    by_model: dict[str, float] = {}
    if key_id:
        mine = [r for r in rows if r.group.api_key_id == key_id]
        cadbot = sum(_usd(r.cost.amount) for r in mine)
        for r in mine:
            model = r.group.model or "other"
            by_model[model] = by_model.get(model, 0.0) + _usd(r.cost.amount)
    return BilledCost(since, until, key_id, key_name, cadbot, organization, by_model)
