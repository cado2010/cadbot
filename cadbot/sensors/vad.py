# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Voice activity detection: Silero VAD (ONNX, no PyTorch) plus a speech segmenter.

The Silero v6 model ships inside faster-whisper, so no separate package (and no PyTorch)
is needed. The segmenter cuts the stream into utterances; a turn ends after ~700 ms of
silence.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np

FRAME = 512  # samples per frame at 16 kHz (32 ms), what Silero expects
CONTEXT = 64
FRAME_MS = FRAME * 1000 // 16_000


def default_model_path() -> Path:
    from faster_whisper.utils import get_assets_path

    return Path(get_assets_path()) / "silero_vad_v6.onnx"


class SileroVad:
    """Streaming Silero VAD: call with one 512-sample frame, get a speech probability."""

    def __init__(self, model_path: Path | None = None) -> None:
        import onnxruntime

        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 4
        self._session = onnxruntime.InferenceSession(
            str(model_path or default_model_path()), providers=["CPUExecutionProvider"],
            sess_options=opts)
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros(CONTEXT, dtype=np.float32)

    def __call__(self, frame: np.ndarray) -> float:
        if frame.size != FRAME:
            raise ValueError(f"VAD frames must be {FRAME} samples, got {frame.size}")
        x = np.concatenate([self._context, frame.astype(np.float32)])[None, :]
        prob, self._h, self._c = self._session.run(None, {"input": x, "h": self._h, "c": self._c})
        self._context = x[0, -CONTEXT:]
        return float(np.asarray(prob).reshape(-1)[0])


@dataclass(frozen=True)
class SpeechStart:
    pass


@dataclass(frozen=True)
class SpeechEnd:
    audio: np.ndarray
    speech_s: float
    """Seconds of speech in the segment (frames above the threshold)."""


@dataclass(frozen=True)
class SpeechDiscarded:
    """Speech started but was too short to be an utterance (a cough, a click)."""


VadEvent = SpeechStart | SpeechEnd | SpeechDiscarded


@dataclass(frozen=True)
class SegmenterConfig:
    threshold: float = 0.5
    end_silence_ms: int = 700
    min_speech_ms: int = 250
    max_utterance_s: float = 30.0
    pre_roll_ms: int = 300
    keep_trailing_ms: int = 200

    @property
    def neg_threshold(self) -> float:
        return max(0.01, self.threshold - 0.15)


class SpeechSegmenter:
    def __init__(self, config: SegmenterConfig) -> None:
        self.cfg = config
        self._pre_roll: deque[np.ndarray] = deque(maxlen=max(1, config.pre_roll_ms // FRAME_MS))
        self.reset()

    @property
    def active(self) -> bool:
        return self._active

    @property
    def speech_s(self) -> float:
        return self._speech_frames * FRAME_MS / 1000

    def reset(self) -> None:
        self._active = False
        self._frames: list[np.ndarray] = []
        self._speech_frames = 0
        self._silence_frames = 0
        self._pre_roll.clear()

    def push(self, frame: np.ndarray, prob: float) -> list[VadEvent]:
        if not self._active:
            if prob >= self.cfg.threshold:
                self._active = True
                self._frames = [*self._pre_roll, frame]
                self._speech_frames, self._silence_frames = 1, 0
                self._pre_roll.clear()
                return [SpeechStart()]
            self._pre_roll.append(frame)
            return []
        self._frames.append(frame)
        if prob >= self.cfg.threshold:
            self._speech_frames += 1
            self._silence_frames = 0
        elif prob < self.cfg.neg_threshold:
            self._silence_frames += 1
        too_long = len(self._frames) * FRAME_MS >= self.cfg.max_utterance_s * 1000
        if self._silence_frames * FRAME_MS >= self.cfg.end_silence_ms or too_long:
            return [self._finish()]
        return []

    def _finish(self) -> VadEvent:
        drop = max(0, self._silence_frames - self.cfg.keep_trailing_ms // FRAME_MS)
        frames = self._frames[: len(self._frames) - drop] if drop else self._frames
        speech_s = self.speech_s
        self.reset()
        if speech_s * 1000 < self.cfg.min_speech_ms:
            return SpeechDiscarded()
        return SpeechEnd(audio=np.concatenate(frames), speech_s=speech_s)
