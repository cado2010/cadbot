# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Model and voice files: `python -m cadbot.models ensure` downloads and verifies them."""

from __future__ import annotations

from pathlib import Path

from cadbot.models.manifest import VOICE_FILES, WHISPER_DIR


def whisper_dir(models_dir: Path, model: str | None = None) -> Path:
    """Folder of a downloaded faster-whisper model ('small.en' by default, or 'tiny.en')."""
    return models_dir / WHISPER_DIR if model is None else models_dir / "whisper" / model


def voice_files(models_dir: Path) -> dict[str, Path]:
    return {lang: models_dir / rel for lang, rel in VOICE_FILES.items()}
