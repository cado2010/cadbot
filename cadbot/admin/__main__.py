# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Owner commands, run on the device:

    python -m cadbot.admin people
    python -m cadbot.admin forget --name Raj        (asks for confirmation)
    python -m cadbot.admin forget --id p_1a2b3c4d --yes
    python -m cadbot.admin spend [--days N]         (what cadbot has cost)

Stop cadbot first, or restart it afterwards, so it reloads the people it knows.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime, timedelta

import truststore

from cadbot.config import Config, load_config
from cadbot.people.store import PeopleStore, StoredPerson
from cadbot.platform import Platform, get_platform
from cadbot.usage import KINDS, UsageLog, period_starts


def open_store() -> PeopleStore:
    data = get_platform().paths.data_dir
    return PeopleStore(data / "cadbot.db", data / "faces")


def describe(p: StoredPerson) -> str:
    keep = "permanent" if p.permanent else "until they say 'forget me'"
    return (f"{p.person_id}  {p.name or '(no name)':<20} {len(p.views)} view(s), "
            f"last seen {p.last_seen or 'never'}, kept {keep}. {p.description}")


def cmd_people(store: PeopleStore) -> int:
    people = store.load_all()
    if not people:
        print("cadbot doesn't remember anyone.")
    for p in people:
        print(describe(p))
    return 0


def cmd_forget(store: PeopleStore, name: str | None, person_id: str | None, yes: bool) -> int:
    people = store.load_all()
    if person_id:
        matches = [p for p in people if p.person_id == person_id]
    else:
        wanted = (name or "").lower()
        matches = [p for p in people if p.name and wanted in p.name.lower()]
    if not matches:
        print("No match.")
        return 1
    if len(matches) > 1:
        print("Several people match; use --id:")
        for p in matches:
            print("  " + describe(p))
        return 1
    person = matches[0]
    print("This erases, and can't be undone:\n  " + describe(person))
    if not yes and input("Type 'yes' to confirm: ").strip().lower() != "yes":
        print("Cancelled.")
        return 1
    report = store.erase(person.person_id)
    print(f"Erased {report.name or report.person_id}: {report.views} face view(s), "
          f"{report.thumbnails} thumbnail file(s).")
    return 0


def cmd_spend(days: int | None) -> int:
    """cadbot's own (real-time, estimated) log, then the billed amount from the account."""
    platform = get_platform()
    config = load_config(platform.name, platform.paths.config_dir)
    usage = UsageLog(platform.paths.data_dir / "cadbot.db", config.pricing)
    print("cadbot's own log (estimated from token counts, real time):")
    for label, since in period_starts().items():
        totals = usage.totals(since)
        print(f"  {label:<12} ${sum(t.cost_usd for t in totals):8.2f}")
        for t in totals:
            images = f", {t.images} with images" if t.images else ""
            print(f"      {KINDS.get(t.kind, t.kind):<34} ${t.cost_usd:8.2f}  "
                  f"({t.requests} requests{images}, {t.tokens.web_searches} web searches)")
    usage.close()
    return report_billed(platform, config, days)


def report_billed(platform: Platform, config: Config, days: int | None) -> int:
    from cadbot.account import admin_client, billed_cost, find_key

    admin_key = platform.paths.get_secret("ANTHROPIC_ADMIN_KEY")
    print()
    if not admin_key:
        print("Billed amount from your Anthropic account: add an Admin API key to .env as "
              "ANTHROPIC_ADMIN_KEY=sk-ant-admin... (Console > Settings > Admin keys) to see it.")
        return 0
    now = datetime.now(UTC)
    if days:
        since = now - timedelta(days=min(days, 31))
        label = f"last {min(days, 31)} days"
    else:
        since = period_starts()["this month"].astimezone(UTC)
        label = "this month"
    client = admin_client(admin_key)
    key_id, key_name = config.account.api_key_id, None
    if key_id is None:
        api_key = platform.paths.get_secret("ANTHROPIC_API_KEY") or ""
        found = find_key(client, api_key) if api_key else None
        if found:
            key_id, key_name = found
    try:
        cost = billed_cost(client, since, now, key_id, key_name)
    except Exception as exc:
        print(f"Couldn't read the account's costs: {type(exc).__name__}: {exc}")
        return 1
    print(f"Billed by Anthropic, {label} (lags a few hours; before credits):")
    if cost.cadbot_usd is not None:
        name = f" ({key_name})" if key_name else ""
        print(f"  cadbot's API key{name}: ${cost.cadbot_usd:.2f}")
        for model, usd in sorted(cost.by_model.items(), key=lambda kv: -kv[1]):
            print(f"      {model:<30} ${usd:.2f}")
    else:
        print("  cadbot's API key: not identified (set account.api_key_id in config.yaml)")
    print(f"  whole organization: ${cost.organization_usd:.2f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cadbot.admin")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("people", help="list the people cadbot remembers")
    forget = sub.add_parser("forget", help="erase a person completely")
    target = forget.add_mutually_exclusive_group(required=True)
    target.add_argument("--name")
    target.add_argument("--id")
    forget.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    spend = sub.add_parser("spend", help="what cadbot has cost (local log and account)")
    spend.add_argument("--days", type=int, help="account figures for the last N days (max 31) "
                                                "instead of this month")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    if args.command == "spend":
        truststore.inject_into_ssl()
        return cmd_spend(args.days)
    store = open_store()
    try:
        if args.command == "people":
            return cmd_people(store)
        return cmd_forget(store, args.name, args.id, args.yes)
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
