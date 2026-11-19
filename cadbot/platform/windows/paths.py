# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Windows folders under %LOCALAPPDATA% (cadbot). Secrets from the environment, .env or keyring."""

from __future__ import annotations

from pathlib import Path

from platformdirs import user_cache_dir, user_data_dir

from cadbot.platform.common.paths import DirPaths


def make_paths() -> DirPaths:
    data = Path(user_data_dir("cadbot", appauthor=False, roaming=False))
    return DirPaths(
        data_dir=data,
        config_dir=data,
        cache_dir=Path(user_cache_dir("cadbot", appauthor=False)),
        secrets_file=Path.cwd() / ".env",
        use_keyring=True,
    )
