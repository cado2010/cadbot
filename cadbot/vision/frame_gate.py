# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""The frame gate: decides only *when* a frame is worth sending to Claude, never what it shows.

A cost control, not a judgement: send when enough pixels changed since the last frame
sent, when a new face appears, or at the heartbeat interval Claude chose.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class GateConfig:
    pixel_delta: int = 25
    change_fraction: float = 0.03
    min_interval_s: float = 10.0
    watch_interval_s: float = 300.0


def changed_fraction(a: np.ndarray, b: np.ndarray, pixel_delta: int) -> float:
    return float(np.count_nonzero(cv2.absdiff(a, b) > pixel_delta)) / a.size


class FrameGate:
    MIN_WATCH_S, MAX_WATCH_S = 10.0, 3600.0

    def __init__(self, config: GateConfig) -> None:
        self.cfg = config
        self._last_sent: np.ndarray | None = None
        self._last_sent_at: float | None = None

    @property
    def watch_interval_s(self) -> float:
        return self.cfg.watch_interval_s

    def set_watch_interval(self, seconds: float) -> float:
        """Claude's choice of heartbeat, clamped to a sane range. Returns the value used."""
        self.cfg.watch_interval_s = min(self.MAX_WATCH_S, max(self.MIN_WATCH_S, seconds))
        return self.cfg.watch_interval_s

    def check(self, grey: np.ndarray, now: float, new_face: bool = False) -> str | None:
        """The reason to send this frame now, or None."""
        if self._last_sent is None or self._last_sent_at is None:
            return "first frame"
        since = now - self._last_sent_at
        if since >= self.cfg.watch_interval_s:
            return "heartbeat"
        if since < self.cfg.min_interval_s:
            return None
        if new_face:
            return "a new face appeared"
        if changed_fraction(grey, self._last_sent, self.cfg.pixel_delta) > \
                self.cfg.change_fraction:
            return "the scene changed"
        return None

    def mark_sent(self, grey: np.ndarray, now: float) -> None:
        self._last_sent = grey
        self._last_sent_at = now

    def motion(self, previous: np.ndarray | None, grey: np.ndarray) -> bool:
        """Is anything moving right now? (Steers how often faces are analysed.)"""
        if previous is None:
            return True
        return changed_fraction(grey, previous, self.cfg.pixel_delta) > 0.005
