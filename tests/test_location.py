# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Location: sources, address lookup, caching, moving, and how Claude gets it.

The web services are faked with httpx.MockTransport: no real lookups in tests.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from cadbot.agent.tools import build_registry
from cadbot.bus import LocationChanged, Utterance
from cadbot.config import AgentConfig, LocationConfig
from cadbot.location import Location, LocationService, LocationStore, distance_km, usable_aps
from cadbot.platform.base import WifiAP
from cadbot.platform.fake import FakeWifiScanner
from cadbot.platform.windows.wifi import parse_netsh
from cadbot.router import render_event, set_timezone
from tests.fakes.claude import reply, tool_use
from tests.fakes.harness import AgentHarness, utterance

CHICAGO = (41.8781, -87.6298)
NOMINATIM = {"display_name": "233 South Wacker Drive, Chicago, Illinois, 60606, United States",
             "address": {"city": "Chicago", "state": "Illinois", "country": "United States",
                         "country_code": "us"}}


class FakeWeb:
    """Answers beaconDB and Nominatim requests; records what was sent."""

    def __init__(self, position: tuple[float, float] = CHICAGO, fallback: str | None = None,
                 found: bool = True) -> None:
        self.position, self.fallback, self.found = position, fallback, found
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if "geolocate" in request.url.path:
            if not self.found:
                return httpx.Response(404, json={"error": {"reason": "notFound"}})
            body: dict[str, Any] = {"location": {"lat": self.position[0],
                                                 "lng": self.position[1]}, "accuracy": 40.0}
            if self.fallback:
                body |= {"fallback": self.fallback, "accuracy": 25_000.0}
            return httpx.Response(200, json=body)
        return httpx.Response(200, json=NOMINATIM)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler),
                                 headers={"User-Agent": "cadbot-test"})

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if r.method == "POST"]


APS = [WifiAP("aa:bb:cc:00:00:01", -50, "Home"), WifiAP("aa:bb:cc:00:00:02", -70, "Cafe"),
       WifiAP("aa:bb:cc:00:00:03", -60, ""), WifiAP("aa:bb:cc:00:00:04", -55, "Shop_nomap")]


@pytest.fixture
def store(tmp_path: Path) -> Iterator[LocationStore]:
    s = LocationStore(tmp_path / "cadbot.db")
    yield s
    s.close()


def service(store: LocationStore, web: FakeWeb, aps: list[WifiAP] | None = None,
            moved: list[tuple[Any, Any]] | None = None, **cfg: Any) -> LocationService:
    sink = moved if moved is not None else []
    return LocationService(LocationConfig(**cfg), store, FakeWifiScanner(aps or []),
                           client_factory=web.client,
                           on_moved=lambda a, b: sink.append((a, b)))


async def test_wifi_location_with_address_and_timezone(store: LocationStore) -> None:
    web = FakeWeb()
    loc = await service(store, web, APS).refresh()
    assert loc is not None and loc.source == "wifi"
    assert (loc.city, loc.region, loc.country_code) == ("Chicago", "Illinois", "US")
    assert loc.address is not None and "Wacker" in loc.address
    assert loc.timezone == "America/Chicago"  # worked out offline
    sent = web.bodies()[0]["wifiAccessPoints"]
    assert [ap["macAddress"] for ap in sent] == ["aa:bb:cc:00:00:01", "aa:bb:cc:00:00:02"]
    assert sent[0]["signalStrength"] == -50  # hidden and _nomap networks were never sent


async def test_ip_fallback_gives_no_street_address(store: LocationStore) -> None:
    web = FakeWeb(fallback="ipf")
    loc = await service(store, web, aps=[]).refresh()
    assert loc is not None and loc.source == "ip" and loc.address is None
    assert loc.city == "Chicago"
    assert "wifiAccessPoints" not in web.bodies()[0] and web.bodies()[0]["considerIp"] is True
    reverse = next(r for r in web.requests if r.method == "GET")
    assert reverse.url.params["zoom"] == "10"


async def test_manual_location_sends_nothing(store: LocationStore) -> None:
    web = FakeWeb()
    loc = await service(store, web, APS, latitude=51.5072, longitude=-0.1276, city="London",
                        region="England", country_code="gb").refresh()
    assert loc is not None and loc.source == "manual" and loc.city == "London"
    assert loc.country_code == "GB" and loc.timezone == "Europe/London"
    assert web.requests == []


async def test_nothing_found_keeps_the_cached_location(store: LocationStore) -> None:
    first = await service(store, FakeWeb(), APS).refresh()
    again = service(store, FakeWeb(found=False), APS)
    assert again.current == first  # loaded from the database
    assert await again.refresh() == first


async def test_ip_lookup_can_be_turned_off(store: LocationStore) -> None:
    web = FakeWeb()
    assert await service(store, web, aps=[], ip_fallback=False).refresh() is None
    assert web.requests == []


async def test_small_moves_reuse_the_address_big_moves_are_reported(
        store: LocationStore) -> None:
    moved: list[tuple[Any, Any]] = []
    await service(store, FakeWeb(), APS, moved).refresh()
    nearby = FakeWeb(position=(41.8790, -87.6300))  # ~100 m away
    svc = service(store, nearby, APS, moved)
    await svc.refresh()
    assert [r.method for r in nearby.requests] == ["POST"]  # no new address lookup
    assert moved == []
    far = FakeWeb(position=(30.2672, -97.7431))  # Austin
    svc = service(store, far, APS, moved)
    await svc.refresh()
    assert len(moved) == 1 and moved[0][0].city == "Chicago"


def test_staleness_and_labels() -> None:
    loc = Location(*CHICAGO, 40.0, "wifi", "2026-11-01T10:00:00+00:00", city="Chicago",
                   region="Illinois", country_code="US", timezone="America/Chicago")
    assert loc.label == "Chicago, Illinois"
    assert loc.user_location() == {"type": "approximate", "city": "Chicago",
                                   "region": "Illinois", "country": "US",
                                   "timezone": "America/Chicago"}
    assert Location(1.0, 2.0, None, "ip", "x").user_location() is None
    assert 1550 < distance_km(CHICAGO, (30.2672, -97.7431)) < 1600  # Chicago-Austin


def test_usable_access_points() -> None:
    assert [a.ssid for a in usable_aps(APS)] == ["Home", "Cafe"]


def test_netsh_parser() -> None:
    out = """Interface name : Wi-Fi
SSID 1 : Home
    Network type            : Infrastructure
    BSSID 1                 : AA:BB:CC:DD:EE:01
         Signal             : 80%
         Channel            : 11
    BSSID 2                 : aa:bb:cc:dd:ee:02
         Signal             : 30%
SSID 2 :
    BSSID 1                 : aa:bb:cc:dd:ee:03
         Signal             : 50%
"""
    aps = parse_netsh(out)
    assert [(a.bssid, a.rssi_dbm, a.ssid) for a in aps] == [
        ("aa:bb:cc:dd:ee:01", -60, "Home"), ("aa:bb:cc:dd:ee:02", -85, "Home"),
        ("aa:bb:cc:dd:ee:03", -75, "")]


def test_events_carry_place_and_local_time() -> None:
    set_timezone("America/Chicago")
    try:
        event = Utterance("hi", datetime.fromisoformat("2026-11-19T20:00:00+00:00"), 1.0)
        text = render_event(event, place="Chicago, Illinois")[0]["text"]
        assert "2:00 pm" in text and "Location: Chicago, Illinois." in text
        moved = render_event(LocationChanged("Chicago, Illinois", "Austin, Texas", 1570))[0]
        assert "moved from Chicago, Illinois to Austin, Texas" in moved["text"]
    finally:
        set_timezone(None)


def test_web_search_knows_the_area() -> None:
    area = {"type": "approximate", "city": "Chicago", "country": "US"}
    def search_tool(registry_defs: list[dict[str, object]]) -> dict[str, object]:
        return next(t for t in registry_defs if t["name"] == "web_search")

    assert search_tool(build_registry(AgentConfig(), area).api_definitions())[
        "user_location"] == area
    assert "user_location" not in search_tool(build_registry(AgentConfig()).api_definitions())


async def test_get_location_tool(harness: AgentHarness, store: LocationStore) -> None:
    svc = service(store, FakeWeb(), APS)
    await svc.refresh()
    original = harness.agent.make_context

    def with_location(turn: Any) -> Any:
        ctx = original(turn)
        ctx.location = svc
        return ctx

    harness.agent.make_context = with_location
    harness.agent.place = svc.label
    harness.client.script = [reply(tool_use("get_location")), reply()]
    await harness.agent.handle(utterance("where are we exactly?"))
    first = harness.client.requests[0]["messages"][0]["content"][-1]["text"]
    assert "Location: Chicago, Illinois." in first
    result = harness.client.requests[-1]["messages"][-1]["content"][0]["content"]
    assert "Wacker" in result and "America/Chicago" in result and "Never say" in result
