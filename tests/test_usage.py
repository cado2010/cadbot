# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Spend tracking: the local usage log, the agent recording it, and the account query."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from cadbot.account import billed_cost, find_key, hint_matches
from cadbot.bus import Observation
from cadbot.config import PricingConfig
from cadbot.usage import Tokens, UsageLog, summary_text, tokens_from_usage
from tests.fakes.claude import reply, tool_use
from tests.fakes.harness import AgentHarness, make_harness, utterance
from tests.fakes.vision import face, frame

PRICES = PricingConfig()


def usage(**kw: Any) -> SimpleNamespace:
    base: dict[str, Any] = dict(input_tokens=0, output_tokens=0, cache_creation_input_tokens=0,
                                cache_read_input_tokens=0, server_tool_use=None, iterations=None)
    return SimpleNamespace(**(base | kw))


@pytest.fixture
def log(tmp_path: Path) -> Iterator[UsageLog]:
    ul = UsageLog(tmp_path / "cadbot.db", PRICES)
    yield ul
    ul.close()


def test_cost_from_tokens() -> None:
    t = Tokens(input=1_000_000, cache_write=1_000_000, cache_read=1_000_000,
               output=1_000_000, web_searches=1000)
    assert t.cost(PRICES) == pytest.approx(4 + 5 + 0.2 + 20 + 10)


def test_compaction_tokens_are_counted() -> None:
    u = usage(input_tokens=100, output_tokens=10,
              server_tool_use=SimpleNamespace(web_search_requests=2, web_fetch_requests=0),
              iterations=[SimpleNamespace(type="message", input_tokens=100, output_tokens=10),
                          SimpleNamespace(type="compaction", input_tokens=5000,
                                          output_tokens=800, cache_creation_input_tokens=0,
                                          cache_read_input_tokens=0)])
    assert tokens_from_usage(u) == Tokens(5100, 0, 0, 810, 2)


def test_totals_by_kind_and_period(log: UsageLog) -> None:
    now = datetime.now(UTC)
    log.record("camera", True, "claude-opus-5-5", usage(input_tokens=1_000_000))
    log.record("speech", False, "claude-opus-5-5", usage(output_tokens=100_000))
    log.record("camera", True, "claude-opus-5-5", usage(input_tokens=1_000_000),
               at=now - timedelta(days=40))
    totals = {t.kind: t for t in log.totals(now - timedelta(hours=1))}
    assert totals["camera"].cost_usd == pytest.approx(4.0) and totals["camera"].images == 1
    assert totals["speech"].cost_usd == pytest.approx(2.0)
    assert len(log.totals(now - timedelta(days=60))) == 2
    assert "camera $4.00 (1 requests, 1 with images)" in summary_text(log)


async def test_agent_records_each_request(tmp_path: Path) -> None:
    h = make_harness(with_vision=True)
    ul = UsageLog(tmp_path / "cadbot.db", PRICES)
    h.agent.usage_log = ul
    assert h.reader is not None and h.analyzer is not None and h.vision is not None
    h.analyzer.faces = [face(1)]
    h.reader.push(frame())
    await h.vision.step()
    h.client.script = [reply(), reply(tool_use("speak", text="Hi.")), reply()]
    await h.agent.handle(Observation(h.vision.snapshot(), "heartbeat"))  # type: ignore[arg-type]
    await h.agent.handle(utterance("hello"))
    totals = {t.kind: t for t in ul.totals(datetime.now(UTC) - timedelta(days=1))}
    assert totals["camera"].requests == 1 and totals["camera"].images == 1
    assert totals["speech"].requests == 2  # the tool round counts too
    ul.close()


async def test_get_costs_tool(harness: AgentHarness, tmp_path: Path) -> None:
    ul = UsageLog(tmp_path / "cadbot.db", PRICES)
    ul.record("camera", True, "claude-opus-5-5", usage(input_tokens=250_000))
    original = harness.agent.make_context

    def with_usage(turn: Any) -> Any:
        ctx = original(turn)
        ctx.usage = ul
        return ctx

    harness.agent.make_context = with_usage
    harness.client.script = [reply(tool_use("get_costs")), reply()]
    await harness.agent.handle(utterance("how much have you cost today?"))
    result = harness.client.requests[-1]["messages"][-1]["content"][0]["content"]
    assert "today: about $1.00" in result and "camera" in result
    ul.close()


def test_key_hint_matching() -> None:
    key = "sk-ant-api03-ABCDEFGH" + "x" * 80 + "igAA"
    assert hint_matches("sk-ant-api03-ABC...igAA", key)
    assert hint_matches("sk-ant-api03-ABC…igAA", key)
    assert not hint_matches("sk-ant-api03-XYZ...igAA", key)
    assert not hint_matches(None, key)


class FakeAdmin:
    """Mimics client.beta.organization.{api_keys,analytics.cost}.list."""

    def __init__(self, rows: list[SimpleNamespace], keys: list[SimpleNamespace]) -> None:
        self.calls: list[dict[str, Any]] = []

        def cost_list(**kw: Any) -> list[SimpleNamespace]:
            self.calls.append(kw)
            return rows

        org = SimpleNamespace(
            api_keys=SimpleNamespace(list=lambda **kw: keys),
            analytics=SimpleNamespace(cost=SimpleNamespace(list=cost_list)))
        self.beta = SimpleNamespace(organization=org)


def row(key_id: str, model: str, cents: str) -> SimpleNamespace:
    return SimpleNamespace(group=SimpleNamespace(api_key_id=key_id, model=model),
                           cost=SimpleNamespace(amount=cents))


def test_billed_cost_for_cadbots_key() -> None:
    admin: Any = FakeAdmin(
        [row("apikey_cad", "claude-opus-5-5", "250.5"), row("apikey_cad", "claude-opus-5", "10"),
         row("apikey_other", "claude-opus-5-5", "1000")],
        [SimpleNamespace(id="apikey_cad", name="cadbot-pc",
                         partial_key_hint="sk-ant-api03-AB...yz")])
    assert find_key(admin, "sk-ant-api03-ABCDEF" + "q" * 40 + "xyz") == ("apikey_cad",
                                                                           "cadbot-pc")
    since = datetime.now(UTC) - timedelta(days=3)
    cost = billed_cost(admin, since, key_id="apikey_cad")
    assert cost.cadbot_usd == pytest.approx(2.605)
    assert cost.organization_usd == pytest.approx(12.605)
    assert cost.by_model == {"claude-opus-5-5": pytest.approx(2.505),
                             "claude-opus-5": pytest.approx(0.10)}
    assert admin.calls[0]["group_by"] == ["api_key_id", "model"]
    with pytest.raises(ValueError):
        billed_cost(admin, since - timedelta(days=40), key_id="apikey_cad")


def test_admin_spend_without_an_admin_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    from cadbot.admin.__main__ import main as admin
    from cadbot.platform import get_platform

    monkeypatch.setenv("CADBOT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_ADMIN_KEY", raising=False)
    get_platform.cache_clear()
    try:
        assert admin(["spend"]) == 0
    finally:
        get_platform.cache_clear()
    out = capsys.readouterr().out
    assert "cadbot's own log" in out and "ANTHROPIC_ADMIN_KEY" in out
