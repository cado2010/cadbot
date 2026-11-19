# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Text-to-speech with Piper (GPL-3.0). One voice per language; voices load on first use."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)


class Synthesizer(Protocol):
    def languages(self) -> list[str]: ...
    def synthesize(self, text: str, lang: str) -> tuple[np.ndarray, int]:
        """Blocking: mono float32 samples and their sample rate."""
        ...


class PiperTTS:
    def __init__(self, voice_files: dict[str, Path]) -> None:
        self._files = voice_files
        self._voices: dict[str, object] = {}
        self._lock = threading.Lock()

    def languages(self) -> list[str]:
        return sorted(self._files)

    def _voice(self, lang: str):  # type: ignore[no-untyped-def]
        with self._lock:
            if lang not in self._voices:
                from piper import PiperVoice

                path = self._files[lang]
                log.info("loading Piper voice %s", path.name)
                self._voices[lang] = PiperVoice.load(path)
            return self._voices[lang]

    def synthesize(self, text: str, lang: str) -> tuple[np.ndarray, int]:
        voice = self._voice(lang)
        chunks = list(voice.synthesize(text))  # type: ignore[attr-defined]
        if not chunks:
            return np.zeros(0, dtype=np.float32), 22_050
        audio = np.concatenate([c.audio_float_array.astype(np.float32) for c in chunks])
        return audio, chunks[0].sample_rate
