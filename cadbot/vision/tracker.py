# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Follows each face from frame to frame with a track id, so an identity holds while the
person turns away or walks across the room.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np

from cadbot.vision.faces import Angle, DetectedFace

MatchLevel = str  # "confident" | "not sure" | "unknown"


@dataclass
class Identity:
    person_id: str
    score: float
    level: MatchLevel


@dataclass
class Track:
    track_id: int
    box: tuple[int, int, int, int]
    angle: Angle
    embedding: np.ndarray
    last_seen: float
    first_seen: float
    detection_score: float = 0.0
    identity: Identity | None = None
    """Best match so far; a confident identity sticks while the track lives."""
    last_match: Identity | None = None
    """The match for the most recent frame."""
    _challenger: tuple[str, int] = field(default=("", 0))

    @property
    def centre(self) -> tuple[float, float]:
        x, y, w, h = self.box
        return x + w / 2, y + h / 2

    def update_identity(self, match: Identity | None, switch_after: int = 3) -> None:
        """Keep the best identity for this track.

        Before a confident match, the best score wins. Once confident, the identity only
        changes if someone else matches confidently `switch_after` frames in a row; a
        face turned away (no match) never clears it.
        """
        self.last_match = match
        if match is None:
            return
        current = self.identity
        if current is None or current.level != "confident":
            if current is None or match.level == "confident" or match.score > current.score:
                self.identity = match
            return
        if match.person_id == current.person_id:
            if match.level == "confident":
                current.score = match.score
            self._challenger = ("", 0)
            return
        if match.level != "confident":
            return
        name, count = self._challenger
        count = count + 1 if name == match.person_id else 1
        self._challenger = (match.person_id, count)
        if count >= switch_after:
            self.identity = match
            self._challenger = ("", 0)


def iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


class Tracker:
    def __init__(self, timeout_s: float = 2.0, min_similarity: float = 0.3) -> None:
        self.timeout_s = timeout_s
        self.min_similarity = min_similarity
        self.tracks: dict[int, Track] = {}
        self._ids = itertools.count(1)

    def update(self, faces: list[DetectedFace], now: float) -> tuple[list[Track], list[Track]]:
        """Assign detections to tracks. Returns (tracks seen this frame, new tracks)."""
        pairs = []
        for t in self.tracks.values():
            for i, f in enumerate(faces):
                overlap = iou(t.box, f.box)
                similarity = float(np.dot(t.embedding, f.embedding))
                if overlap > 0.1 or similarity > 0.5:
                    pairs.append((overlap + max(0.0, similarity), t.track_id, i))
        pairs.sort(reverse=True)
        used_tracks: set[int] = set()
        used_faces: set[int] = set()
        seen: list[Track] = []
        for _score, tid, i in pairs:
            if tid in used_tracks or i in used_faces:
                continue
            track, face = self.tracks[tid], faces[i]
            if float(np.dot(track.embedding, face.embedding)) < self.min_similarity \
                    and iou(track.box, face.box) < 0.3:
                continue
            used_tracks.add(tid)
            used_faces.add(i)
            track.box, track.angle, track.embedding = face.box, face.angle, face.embedding
            track.last_seen, track.detection_score = now, face.score
            seen.append(track)
        new: list[Track] = []
        for i, face in enumerate(faces):
            if i in used_faces:
                continue
            track = Track(next(self._ids), face.box, face.angle, face.embedding, now, now,
                          face.score)
            self.tracks[track.track_id] = track
            seen.append(track)
            new.append(track)
        for tid in [t for t, tr in self.tracks.items() if now - tr.last_seen > self.timeout_s]:
            del self.tracks[tid]
        return seen, new

    def get(self, track_id: int) -> Track | None:
        return self.tracks.get(track_id)

    def visible(self) -> list[Track]:
        return sorted(self.tracks.values(), key=lambda t: t.track_id)
