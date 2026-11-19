# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Small numpy helpers for audio: resampling and levels. No hardware access."""

from __future__ import annotations

import numpy as np


def resample(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Resample mono float32 audio.

    Integer down-sampling (48 kHz -> 16 kHz) averages groups of samples, which also acts
    as a crude low-pass filter. Other ratios use linear interpolation, which is fine for
    speech.
    """
    samples = np.asarray(samples, dtype=np.float32)
    if src_rate == dst_rate or samples.size == 0:
        return samples
    if src_rate > dst_rate and src_rate % dst_rate == 0:
        factor = src_rate // dst_rate
        usable = samples.size - samples.size % factor
        return samples[:usable].reshape(-1, factor).mean(axis=1).astype(np.float32)
    duration = samples.size / src_rate
    n_out = max(1, round(duration * dst_rate))
    x_old = np.linspace(0.0, duration, num=samples.size, endpoint=False)
    x_new = np.linspace(0.0, duration, num=n_out, endpoint=False)
    return np.interp(x_new, x_old, samples).astype(np.float32)


def rms_level(samples: np.ndarray, gain: float = 4.0) -> float:
    """Loudness 0..1 for the mouth animation."""
    if samples.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float32))))
    return min(1.0, rms * gain)


class ChunkBuffer:
    """Collects arbitrary-sized pieces and hands out fixed-size blocks."""

    def __init__(self, block: int) -> None:
        self.block = block
        self._parts: list[np.ndarray] = []
        self._size = 0

    def push(self, samples: np.ndarray) -> list[np.ndarray]:
        self._parts.append(samples)
        self._size += samples.size
        out: list[np.ndarray] = []
        if self._size < self.block:
            return out
        joined = np.concatenate(self._parts)
        n_blocks = joined.size // self.block
        for i in range(n_blocks):
            out.append(joined[i * self.block : (i + 1) * self.block])
        rest = joined[n_blocks * self.block :]
        self._parts = [rest] if rest.size else []
        self._size = rest.size
        return out
