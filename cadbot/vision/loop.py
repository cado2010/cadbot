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
from dataclasses import dataclass
from datetime import datetime

import cv2
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
PREVIEW_SIZE = (256, 144)
PREVIEW_STALE_S = 2.0


@dataclass(frozen=True)
class PreviewBox:
    """A face in the preview: position as fractions of the preview (already mirrored)."""

    x: float
    y: float
    w: float
    h: float
    status: str  # "known", "unsure" or "unknown"


@dataclass(frozen=True)
class Preview:
    """A small mirrored copy of the camera image for the screen; never stored."""

    rgb: np.ndarray  # (h, w, 3) uint8, C-contiguous
    boxes: tuple[PreviewBox, ...]
    is_night: bool


class FrameReader:
    """Reads the camera on its own thread and keeps only the newest frame.

    `restart()` opens a fresh camera when frames stop (unplugged, a driver stall, another
    app taking the camera). A read stuck inside the driver can't be interrupted, so a stuck
    thread is abandoned (it's a daemon) rather than releasing the camera under it.
    """

    def __init__(self, camera_factory: Callable[[], Camera]) -> None:
        self.camera_factory = camera_factory
        self.camera: Camera | None = None
        self._latest: Frame | None = None
        self._last_frame_at = time.monotonic()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        camera = self.camera_factory()
        camera.open()
        self.camera = camera
        self._stop = threading.Event()
        self._last_frame_at = time.monotonic()
        self._thread = threading.Thread(target=self._run, args=(camera, self._stop),
                                        name="camera", daemon=True)
        self._thread.start()

    def _run(self, camera: Camera, stop: threading.Event) -> None:
        while not stop.is_set():
            frame = camera.read()
            if frame is None:
                time.sleep(0.05)
                continue
            with self._lock:
                if stop.is_set():
                    return
                self._latest = frame
                self._last_frame_at = time.monotonic()
            time.sleep(0.01)

    def latest(self) -> Frame | None:
        with self._lock:
            return self._latest

    def age(self) -> float:
        """Seconds since the last new frame (or since the camera was opened)."""
        with self._lock:
            return time.monotonic() - self._last_frame_at

    def _shutdown(self) -> None:
        self._stop.set()
        thread, camera = self._thread, self.camera
        self._thread, self.camera = None, None
        if thread is not None:
            thread.join(timeout=2)
            if thread.is_alive():
                log.warning("camera read is stuck in the driver; abandoning that connection")
                return
        if camera is not None:
            try:
                camera.close()
            except Exception as exc:  # a dead device can fail to close; we're replacing it
                log.debug("camera close failed: %s", exc)

    def restart(self) -> None:
        self._shutdown()
        with self._lock:
            self._latest = None
        self.start()

    def stop(self) -> None:
        self._shutdown()


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
        self._preview_cache: tuple[int, np.ndarray] | None = None
        self._errors = 0
        self._next_reconnect = 0.0
        self._reconnect_delay = 5.0

    # ------------------------------------------------------------------ main loop

    async def run(self) -> None:
        """Keeps going whatever happens: a bad frame is skipped, a silent camera reopened."""
        connected = await self._connect(self.reader.start, "open")
        try:
            while True:
                busy = False
                try:
                    if not connected or self.reader.age() > self.cfg.camera_stale_s:
                        connected = await self._reconnect()
                    else:
                        busy = await self.step()
                except Exception:
                    self._errors += 1
                    if self._errors in (1, 10) or self._errors % 100 == 0:
                        log.exception("camera frame processing failed (%d so far); "
                                      "carrying on", self._errors)
                await asyncio.sleep(1 / self.cfg.analyze_hz if busy else 0.5)
        finally:
            await asyncio.to_thread(self.reader.stop)

    async def _connect(self, action: Callable[[], None], verb: str) -> bool:
        try:
            await asyncio.to_thread(action)
        except Exception as exc:
            log.warning("camera %s failed: %s", verb, exc)
            return False
        self._reconnect_delay = 5.0
        log.info("camera %s", "connected" if verb == "open" else "reconnected")
        return True

    async def _reconnect(self) -> bool:
        """Frames stopped: forget what was in view, then reopen with growing pauses."""
        if self._frame is not None:
            log.warning("no camera frames for %.0f s; reconnecting", self.reader.age())
            self._lose_sight()
        now = self.clock()
        if now < self._next_reconnect:
            return False
        ok = await self._connect(self.reader.restart, "restart")
        if not ok:
            self._next_reconnect = now + self._reconnect_delay
            self._reconnect_delay = min(60.0, self._reconnect_delay * 2)
        return ok

    def _lose_sight(self) -> None:
        self._frame = None
        self._prev_grey = None
        self.tracker.tracks.clear()
        self._last_face_seen = -1e9
        self.on_gaze(None)

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

    def preview(self) -> Preview | None:
        """The newest frame, small and mirrored like a selfie camera, with face boxes.
        None while the camera is silent, so the screen never shows a frozen picture."""
        frame = self._frame or self.reader.latest()
        if frame is None or self.reader.age() > PREVIEW_STALE_S:
            return None
        key = id(frame)
        if self._preview_cache is None or self._preview_cache[0] != key:
            small = cv2.resize(frame.image, PREVIEW_SIZE, interpolation=cv2.INTER_AREA)
            rgb = np.ascontiguousarray(cv2.flip(small, 1)[..., ::-1])
            self._preview_cache = (key, rgb)
        h, w = frame.image.shape[:2]
        boxes = []
        for track in self.tracker.visible():
            x, y, bw, bh = track.box
            level = track.identity.level if track.identity is not None else "unknown"
            status = {"confident": "known", "not sure": "unsure"}.get(level, "unknown")
            boxes.append(PreviewBox(1 - (x + bw) / w, y / h, bw / w, bh / h, status))
        return Preview(self._preview_cache[1], tuple(boxes), frame.is_night)

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
            if now - self._last_face_seen > self.cfg.gaze_hold_s:  # ride out brief drop-outs
                self.on_gaze(None)
            return
        h, w = frame.image.shape[:2]
        cx, cy = target.centre
        # The camera's left is the viewer's right, so mirror the horizontal position.
        self.on_gaze((-(cx / w * 2 - 1), cy / h * 2 - 1))
