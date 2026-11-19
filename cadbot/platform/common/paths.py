# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Folders and secrets. Values of secrets are never logged."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import dotenv_values

log = logging.getLogger(__name__)


class DirPaths:
    def __init__(self, *, data_dir: Path, config_dir: Path, cache_dir: Path,
                 secrets_file: Path | None = None, use_keyring: bool = False) -> None:
        override = os.environ.get("CADBOT_DATA_DIR")
        self._data = Path(override) if override else data_dir
        self._config = config_dir
        self._cache = cache_dir
        self._secrets_file = secrets_file
        self._use_keyring = use_keyring

    @staticmethod
    def _ensure(path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def data_dir(self) -> Path:
        return self._ensure(self._data)

    @property
    def config_dir(self) -> Path:
        return self._config

    @property
    def cache_dir(self) -> Path:
        return self._ensure(self._cache)

    @property
    def models_dir(self) -> Path:
        override = os.environ.get("CADBOT_MODELS_DIR")
        return self._ensure(Path(override) if override else self._data / "models")

    @property
    def logs_dir(self) -> Path:
        return self._ensure(self._data / "logs")

    def get_secret(self, name: str) -> str | None:
        """Environment first, then the secrets file, then the OS keyring.

        Logs where the value came from (never the value), because a stale environment
        variable silently overrides a good .env entry.
        """
        value = os.environ.get(name)
        if value:
            log.info("%s: using the environment variable", name)
            return value
        if self._secrets_file is not None and self._secrets_file.is_file():
            value = dotenv_values(self._secrets_file).get(name)
            if value:
                log.info("%s: using %s", name, self._secrets_file)
                return value
        if self._use_keyring:
            try:
                import keyring

                value = keyring.get_password("cadbot", name)
            except Exception as exc:  # keyring backends vary; a missing one is not fatal
                log.debug("keyring lookup failed: %s", type(exc).__name__)
                value = None
            if value:
                return value
        return None
