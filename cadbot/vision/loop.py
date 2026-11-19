# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""The camera task: read frames, find and track faces, and send Claude an observation when
the frame gate says a frame is worth it. Frames stay in memory; nothing is written to disk.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime

import numpy as np

from cadbot.bus import Observation, Snapshot
from cadbot.config import VisionConfig
from cadbot.people.registry import PeopleRegistry
from cadbot.platform.base import Camera, Frame
from cadbot.vision.faces import FaceAnalyzer
from cadbot.vision.frame_gate import FrameGate, GateConfig
from cadbot.vision.image import encode_jpeg, face_crop, grey_small, to_jpeg
from cadbot.vision.tracker import Track, Tracker

log = logging.getLogger(__name__)

GazePoint = tuple[float, float] | None


class FrameReader:
    """Reads the camera on its own thread and keeps only the newest frame."""

    def __init__(self, camera: Camera) -> None:
        self.camera = camera
        self._latest: Frame | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.camera.open()
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            frame = self.camera.read()
            if frame is None:
                failures += 1
                if failures in (10, 100):
                    log.warning("camera returned no frame %d times in a row", failures)
                time.sleep(0.05)
                continue
            failures = 0
            with self._lock:
                self._latest = frame
            time.sleep(0.01)

    def latest(self) -> Frame | None:
        with self._lock:
            return self._latest

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self.camera.close()


class VisionLoop:
    def __init__(self, *, reader: FrameReader, analyzer: FaceAnalyzer | None,
                 people: PeopleRegistry, config: VisionConfig,
                 emit: Callable[[Observation], None],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.reader = reader
        self.analyzer = analyzer
        self.people = people
        self.cfg = config
        self.emit = emit
        self.clock = clock
        self.gate = FrameGate(GateConfig(
            pixel_delta=config.gate_pixel_delta, change_fraction=config.gate_change_fraction,
            min_interval_s=config.min_observation_interval_s,
            watch_interval_s=config.default_watch_interval_s))
        self.tracker = Tracker(timeout_s=config.track_timeout_s)
        self.gaze_mode: str = "auto"  # "auto", "off" or "track <id>"
        self.on_gaze: Callable[[GazePoint], None] = lambda _p: None
        self.observations_enabled = True
        self._frame: Frame | None = None
        self._prev_grey: np.ndarray | None = None
        self._last_analysis = -1e9
        self._last_face_seen = -1e9
        self._snapshot_cache: tuple[int, Snapshot] | None = None

    # ------------------------------------------------------------------ main loop

    async def run(self) -> None:
        await asyncio.to_thread(self.reader.start)
        try:
            while True:
                busy = await self.step()
                await asyncio.sleep(1 / self.cfg.analyze_hz if busy else 1.0)
        finally:
            await asyncio.to_thread(self.reader.stop)

    async def step(self) -> bool:
        """Process the newest frame once. Returns True while something is happening."""
        frame = self.reader.latest()
        if frame is None or frame is self._frame:
            return False
        self._frame = frame
        now = self.clock()
        grey = grey_small(frame.image)
        moving = self.gate.motion(self._prev_grey, grey)
        self._prev_grey = grey
        new_tracks: list[Track] = []
        if self.analyzer is not None and (moving or self.tracker.tracks
                                          or now - self._last_analysis >= 1.0):
            self._last_analysis = now
            faces = await asyncio.to_thread(self.analyzer.analyze, frame.image)
            new_tracks = self._update_tracks(faces, frame, now)
        self._update_gaze(frame, now)
        self.people.expire_unsaved(now)
        reason = self._observation_reason(grey, now, new_face=bool(new_tracks))
        if reason:
            self.gate.mark_sent(grey, now)
            self.emit(Observation(self.snapshot(), reason))
        return moving or bool(self.tracker.tracks)

    def _observation_reason(self, grey: np.ndarray, now: float, new_face: bool) -> str | None:
        """Whether to send Claude an observation now, given the cost setting."""
        mode = self.cfg.send_to_claude
        if mode == "none" or not self.observations_enabled:
            return None
        reason = self.gate.check(grey, now, new_face=new_face)
        if mode == "readings" and reason == "the scene changed":
            return None  # without an image a mere scene change tells Claude nothing
        return reason

    def _update_tracks(self, faces: list, frame: Frame, now: float) -> list[Track]:
        seen, new = self.tracker.update(faces, now)
        for track in seen:
            track.update_identity(self.people.match(track.embedding))
        self.people.observe(seen, "night" if frame.is_night else "day", now)
        if seen:
            self._last_face_seen = now
        return new

    # ------------------------------------------------------------------ what Claude gets

    def readings(self) -> str:
        tracks = self.tracker.visible()
        if not tracks:
            return "No faces in view."
        noun = "face" if len(tracks) == 1 else "faces"
        return f"{len(tracks)} {noun} in view: " + " · ".join(
            self.people.describe_track(t) for t in tracks)

    def snapshot(self) -> Snapshot | None:
        frame = self._frame or self.reader.latest()
        if frame is None:
            return None
        key = id(frame)
        if self._snapshot_cache is not None and self._snapshot_cache[0] == key:
            cached = self._snapshot_cache[1]
            return Snapshot(cached.jpeg, cached.taken_at, cached.is_night, self.readings())
        jpeg = None
        if self.cfg.send_to_claude == "images":
            jpeg = to_jpeg(frame.image, quality=self.cfg.jpeg_quality)
        snap = Snapshot(jpeg, datetime.fromtimestamp(frame.timestamp), frame.is_night,
                        self.readings())
        self._snapshot_cache = (key, snap)
        return snap

    def lighting(self) -> str:
        return "night" if self._frame is not None and self._frame.is_night else "day"

    def thumbnail(self, track: Track) -> bytes | None:
        if self._frame is None:
            return None
        return encode_jpeg(face_crop(self._frame.image, track.box))

    def set_watch_interval(self, seconds: float) -> float:
        return self.gate.set_watch_interval(seconds)

    # ------------------------------------------------------------------ eyes that follow

    def _gaze_target(self) -> Track | None:
        tracks = self.tracker.visible()
        if self.gaze_mode == "off" or not tracks:
            return None
        if self.gaze_mode.startswith("track "):
            wanted = self.tracker.get(int(self.gaze_mode.split()[1]))
            if wanted is not None:
                return wanted
        return max(tracks, key=lambda t: t.box[2] * t.box[3])  # nearest = largest face

    def _update_gaze(self, frame: Frame, now: float) -> None:
        target = self._gaze_target()
        if target is None:
            if now - self._last_face_seen > 2.0:  # hold the last direction for ~2 s
                self.on_gaze(None)
            return
        h, w = frame.image.shape[:2]
        cx, cy = target.centre
        # The camera's left is the viewer's right, so mirror the horizontal position.
        self.on_gaze((-(cx / w * 2 - 1), cy / h * 2 - 1))
