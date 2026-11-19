# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""python -m cadbot.models ensure | check | path"""

from __future__ import annotations

import argparse
import logging
import sys

from cadbot.models.download import check, ensure
from cadbot.models.manifest import ModelFile
from cadbot.platform import get_platform


def _progress(entry: ModelFile, done: int, total: int) -> None:
    pct = 100 * done // max(1, total)
    sys.stdout.write(f"\r  {entry.dest}: {pct:3d}% of {total / 1e6:.1f} MB")
    if done >= total:
        sys.stdout.write("\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cadbot.models")
    parser.add_argument("command", choices=["ensure", "check", "path"])
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    models_dir = get_platform().paths.models_dir
    if args.command == "path":
        print(models_dir)
        return 0
    print(f"models folder: {models_dir}")
    statuses = ensure(models_dir, progress=_progress) if args.command == "ensure" \
        else check(models_dir)
    for status in statuses:
        print(f"  [{status.state:>8}] {status.entry.dest}")
    bad = [s for s in statuses if s.state != "ok"]
    print("all models present and verified" if not bad else f"{len(bad)} file(s) not ok")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
