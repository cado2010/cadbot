# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Owner commands, run on the device:

    python -m cadbot.admin people
    python -m cadbot.admin forget --name Raj        (asks for confirmation)
    python -m cadbot.admin forget --id p_1a2b3c4d --yes

Stop cadbot first, or restart it afterwards, so it reloads the people it knows.
"""

from __future__ import annotations

import argparse
import logging
import sys

from cadbot.people.store import PeopleStore, StoredPerson
from cadbot.platform import get_platform


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cadbot.admin")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("people", help="list the people cadbot remembers")
    forget = sub.add_parser("forget", help="erase a person completely")
    target = forget.add_mutually_exclusive_group(required=True)
    target.add_argument("--name")
    target.add_argument("--id")
    forget.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    store = open_store()
    try:
        if args.command == "people":
            return cmd_people(store)
        return cmd_forget(store, args.name, args.id, args.yes)
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
