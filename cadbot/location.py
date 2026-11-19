# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Where cadbot is: position, address, city and timezone, cached so Claude always knows
where "here" is.

Sources, best first: the position set in config.yaml; a Wi-Fi scan located by beaconDB;
beaconDB's IP-address estimate. Addresses come from OpenStreetMap's Nominatim (only when the
position moves; at most one request, with an identifying User-Agent, as its policy asks).
The timezone is worked out offline from the coordinates.
"""

from __future__ import annotations

import asyncio
import logging
import math
import sqlite3
import ssl
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import truststore

from cadbot import __version__
from cadbot.config import LocationConfig
from cadbot.platform.base import WifiAP, WifiScanner

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS location (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    lat REAL NOT NULL, lon REAL NOT NULL, accuracy_m REAL,
    address TEXT, city TEXT, region TEXT, country TEXT, country_code TEXT,
    timezone TEXT, source TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Location:
    lat: float
    lon: float
    accuracy_m: float | None
    source: str  # "manual", "wifi" or "ip"
    updated_at: str
    address: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    country_code: str | None = None
    timezone: str | None = None

    @property
    def label(self) -> str:
        """Short place name for each event, e.g. 'Chicago, Illinois'."""
        parts = [p for p in (self.city, self.region) if p]
        return ", ".join(parts) or self.country or f"{self.lat:.2f}, {self.lon:.2f}"

    def user_location(self) -> dict[str, str] | None:
        """For the web_search tool: approximate location, so 'near me' searches work."""
        if not self.city and not self.country_code:
            return None
        loc: dict[str, str] = {"type": "approximate"}
        for key, value in (("city", self.city), ("region", self.region),
                           ("country", self.country_code), ("timezone", self.timezone)):
            if value:
                loc[key] = value
        return loc


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance between two (lat, lon) points."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def usable_aps(aps: list[WifiAP]) -> list[WifiAP]:
    """Skip hidden networks and any whose name ends in _nomap, as the protocol requires."""
    seen: set[str] = set()
    out = []
    for ap in sorted(aps, key=lambda a: a.rssi_dbm, reverse=True):
        if not ap.ssid or ap.ssid.endswith("_nomap") or ap.bssid in seen:
            continue
        seen.add(ap.bssid)
        out.append(ap)
    return out[:20]


def timezone_at(lat: float, lon: float) -> str | None:
    from timezonefinder import TimezoneFinder

    return TimezoneFinder().timezone_at(lat=lat, lng=lon)


class LocationStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)

    def load(self) -> Location | None:
        with self._lock:
            row = self._db.execute(
                "SELECT lat, lon, accuracy_m, source, updated_at, address, city, region, "
                "country, country_code, timezone FROM location WHERE id = 1").fetchone()
        return Location(*row) if row else None

    def save(self, loc: Location) -> None:
        values = asdict(loc)
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO location (id, lat, lon, accuracy_m, address, city, "
                "region, country, country_code, timezone, source, updated_at) VALUES "
                "(1, :lat, :lon, :accuracy_m, :address, :city, :region, :country, "
                ":country_code, :timezone, :source, :updated_at)", values)

    def close(self) -> None:
        with self._lock:
            self._db.close()


class LocationService:
    def __init__(self, config: LocationConfig, store: LocationStore,
                 wifi: WifiScanner | None,
                 client_factory: Callable[[], httpx.AsyncClient] | None = None,
                 on_moved: Callable[[Location | None, Location], None] = lambda _a, _b: None,
                 ) -> None:
        self.cfg = config
        self.store = store
        self.wifi = wifi
        self.on_moved = on_moved
        self._client_factory = client_factory or self._default_client
        self.current: Location | None = store.load()

    def _default_client(self) -> httpx.AsyncClient:
        agent = f"cadbot/{__version__} (open-source home assistant"
        agent += f"; {self.cfg.contact})" if self.cfg.contact else ")"
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        return httpx.AsyncClient(verify=context, timeout=15, headers={"User-Agent": agent})

    def label(self) -> str | None:
        return self.current.label if self.current else None

    def timezone(self) -> str | None:
        return self.current.timezone if self.current else None

    def is_stale(self, now: datetime | None = None) -> bool:
        if self.current is None:
            return True
        if self.current.source == "manual":
            return False
        updated = datetime.fromisoformat(self.current.updated_at)
        return (now or datetime.now(UTC)) - updated > timedelta(hours=self.cfg.refresh_hours)

    # ------------------------------------------------------------------ refreshing

    async def refresh(self) -> Location | None:
        """Work out the position again; keeps the cached one if every source fails."""
        if not self.cfg.enabled:
            return None
        try:
            async with self._client_factory() as client:
                fresh = await self._locate(client)
                if fresh is not None:
                    fresh = await self._describe(client, fresh)
        except httpx.HTTPError as exc:
            log.warning("location lookup failed: %s", type(exc).__name__)
            return self.current
        if fresh is None:
            return self.current
        previous = self.current
        self.current = fresh
        self.store.save(fresh)
        log.info("location: %s (%s, about %.0f m)", fresh.label, fresh.source,
                 fresh.accuracy_m or 0)
        if previous is not None and distance_km((previous.lat, previous.lon),
                                                (fresh.lat, fresh.lon)) > self.cfg.moved_km:
            self.on_moved(previous, fresh)
        return fresh

    async def _locate(self, client: httpx.AsyncClient) -> Location | None:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        c = self.cfg
        if c.latitude is not None and c.longitude is not None:
            return Location(c.latitude, c.longitude, 10.0, "manual", now, c.address, c.city,
                            c.region, None, c.country_code.upper() if c.country_code else None)
        aps = usable_aps(await asyncio.to_thread(self.wifi.scan)) \
            if self.wifi is not None and c.wifi_lookup else []
        if len(aps) < 2 and not c.ip_fallback:
            log.info("location: fewer than two usable Wi-Fi networks and IP lookup is off")
            return None
        body: dict[str, Any] = {"considerIp": c.ip_fallback}
        if len(aps) >= 2:
            body["wifiAccessPoints"] = [{"macAddress": a.bssid, "signalStrength": a.rssi_dbm}
                                        for a in aps]
        response = await client.post(c.geolocate_url, json=body)
        if response.status_code == 404:
            log.info("location: beaconDB has no estimate here")
            return None
        response.raise_for_status()
        data = response.json()
        source = "ip" if data.get("fallback") == "ipf" or len(aps) < 2 else "wifi"
        return Location(float(data["location"]["lat"]), float(data["location"]["lng"]),
                        float(data.get("accuracy") or 0) or None, source, now)

    async def _describe(self, client: httpx.AsyncClient, loc: Location) -> Location:
        """Address (only when the position moved or was never described) and timezone."""
        timezone = await asyncio.to_thread(timezone_at, loc.lat, loc.lon)
        loc = replace(loc, timezone=timezone)
        previous = self.current
        if loc.city:  # set by hand: nothing to look up
            return loc
        if previous is not None and previous.city and distance_km(
                (previous.lat, previous.lon), (loc.lat, loc.lon)) <= self.cfg.moved_km:
            return replace(loc, address=previous.address, city=previous.city,
                           region=previous.region, country=previous.country,
                           country_code=previous.country_code)
        zoom = 18 if loc.source != "ip" else 10  # no street address from an IP estimate
        response = await client.get(self.cfg.reverse_geocode_url, params={
            "lat": f"{loc.lat:.6f}", "lon": f"{loc.lon:.6f}", "format": "jsonv2",
            "zoom": zoom, "addressdetails": 1})
        response.raise_for_status()
        data = response.json()
        addr = data.get("address", {})
        city = next((addr[k] for k in ("city", "town", "village", "municipality", "suburb")
                     if addr.get(k)), None)
        return replace(loc, address=data.get("display_name") if loc.source != "ip" else None,
                       city=city, region=addr.get("state") or addr.get("county"),
                       country=addr.get("country"),
                       country_code=(addr.get("country_code") or "").upper() or None)

    async def run(self) -> None:
        """Refresh at startup if stale, then whenever the refresh interval passes."""
        while True:
            if self.is_stale():
                await self.refresh()
            await asyncio.sleep(3600)
