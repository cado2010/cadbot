# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Speech-to-text with faster-whisper (`small.en`, int8). GPU if CUDA works, else CPU."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from cadbot.config import SttConfig

log = logging.getLogger(__name__)

_ONLY_PUNCT = re.compile(r"^[\W_]*$")


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str
    no_speech_prob: float = 0.0


class SpeechToText(Protocol):
    def transcribe(self, audio: np.ndarray) -> Transcript | None: ...


def cuda_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


class WhisperTranscriber:
    def __init__(self, model_dir: Path, cfg: SttConfig) -> None:
        self.model_dir = model_dir
        self.cfg = cfg
        self.device = "cpu"
        self._model: Any = None

    def load(self) -> None:
        """Load the model; if CUDA is present but its libraries are missing, fall back to CPU."""
        want_cuda = self.cfg.device == "cuda" or (self.cfg.device == "auto" and cuda_available())
        if want_cuda:
            try:
                self._model = self._make("cuda", self.cfg.compute_type_cuda)
                self._run(np.zeros(16_000, dtype=np.float32))  # missing cuDNN fails here
                self.device = "cuda"
                log.info("Whisper on GPU (%s)", self.cfg.compute_type_cuda)
                return
            except Exception as exc:
                log.warning("Whisper on GPU failed (%s); using the CPU", exc)
        self._model = self._make("cpu", self.cfg.compute_type_cpu)
        self.device = "cpu"
        log.info("Whisper on CPU (%s)", self.cfg.compute_type_cpu)

    def _make(self, device: str, compute_type: str) -> Any:
        from faster_whisper import WhisperModel

        return WhisperModel(str(self.model_dir), device=device, compute_type=compute_type)

    def _run(self, audio: np.ndarray) -> tuple[list[Any], Any]:
        segments, info = self._model.transcribe(
            audio, beam_size=self.cfg.beam_size, language=self.cfg.language, vad_filter=False,
            condition_on_previous_text=False, without_timestamps=True,
            hotwords=self.cfg.hotwords or None)
        return list(segments), info

    def transcribe(self, audio: np.ndarray) -> Transcript | None:
        if self._model is None:
            self.load()
        segments, info = self._run(audio)
        kept = [s for s in segments if s.no_speech_prob < 0.6 or s.avg_logprob > -1.0]
        text = " ".join(s.text.strip() for s in kept).strip()
        if not text or _ONLY_PUNCT.match(text):
            return None
        no_speech = max((s.no_speech_prob for s in kept), default=0.0)
        return Transcript(text=text, language=info.language or "en", no_speech_prob=no_speech)
