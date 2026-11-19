# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Pi folders: /var/lib/cadbot (data), /etc/cadbot (config and secrets.env).

UNTESTED: written before the Raspberry Pi hardware arrived.
"""

from __future__ import annotations

from pathlib import Path

from cadbot.platform.common.paths import DirPaths


def make_paths() -> DirPaths:
    return DirPaths(
        data_dir=Path("/var/lib/cadbot"),
        config_dir=Path("/etc/cadbot"),
        cache_dir=Path("/var/cache/cadbot"),
        secrets_file=Path("/etc/cadbot/secrets.env"),
        use_keyring=False,
    )
