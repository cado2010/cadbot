# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Everyone cadbot can recognise right now: saved people (from the store) plus people held
in memory only (pending consent, said no, or declined to give a name).

Matching is a sensor reading: best cosine similarity against every saved view, reported
as confident / not sure / unknown. Claude decides what it means.
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from cadbot.config import VisionConfig
from cadbot.people.store import Consent, ErasureReport, PeopleStore, View, new_person_id
from cadbot.vision.tracker import Identity, Track

log = logging.getLogger(__name__)

Status = Literal["saved", "pending", "session", "declined"]
"""saved: consented, on disk. pending: name given, waiting for a yes. session: said no, name
used this visit only. declined: gave no name; recognised this session only."""


@dataclass
class Person:
    person_id: str
    name: str | None
    description: str
    status: Status
    views: list[View] = field(default_factory=list)
    permanent: bool = False
    last_seen: float = field(default_factory=time.monotonic)
    last_view_added: float = 0.0
    thumbnail_jpeg: bytes | None = None
    """For unsaved people: held in memory until they agree (then written), else dropped."""
    asked_to_remember: bool = False

    @property
    def label(self) -> str:
        """Name and status, e.g. 'Priya (p_1a2b3c4d' (the caller closes the bracket)."""
        if self.status == "declined":
            return f"visitor ({self.person_id}, gave no name"
        name = self.name or self.person_id
        notes = {"saved": "", "pending": ", not saved: waiting for their yes",
                 "session": ", not saved: said no, this visit only"}[self.status]
        return f"{name} ({self.person_id}{notes}"


class PeopleRegistry:
    def __init__(self, store: PeopleStore, config: VisionConfig) -> None:
        self.store = store
        self.cfg = config
        self.people: dict[str, Person] = {}
        self._last_touch: dict[str, float] = {}

    def load(self) -> int:
        for stored in self.store.load_all():
            self.people[stored.person_id] = Person(
                stored.person_id, stored.name, stored.description, "saved", stored.views,
                stored.permanent)
        log.info("loaded %d saved people", len(self.people))
        return len(self.people)

    # ------------------------------------------------------------------ matching

    def level(self, score: float) -> str:
        if score >= self.cfg.match_confident:
            return "confident"
        return "not sure" if score >= self.cfg.match_maybe else "unknown"

    def match(self, embedding: np.ndarray) -> Identity | None:
        best_id, best = None, -1.0
        for person in self.people.values():
            for view in person.views:
                score = float(np.dot(view.embedding, embedding))
                if score > best:
                    best_id, best = person.person_id, score
        if best_id is None or best < self.cfg.match_maybe:
            return None
        return Identity(best_id, round(best, 2), self.level(best))

    # ------------------------------------------------------------------ remembering

    def remember_pending(self, track: Track, *, name: str | None, description: str,
                         declined: bool, lighting: str,
                         thumbnail_jpeg: bytes | None) -> Person:
        """Hold a person in memory only. Nothing is written until they say yes."""
        existing = self._identity_of(track)
        if existing is not None and existing.status != "saved":
            person = existing  # same visitor, now with a name (or still without)
            person.name = name or person.name
            person.description = description or person.description
            person.status = "declined" if declined and not person.name else "pending"
        else:
            person = Person(new_person_id() if not declined else "v_" + secrets.token_hex(3),
                            name, description, "declined" if declined else "pending")
            self.people[person.person_id] = person
        person.views.append(View(track.embedding, track.angle, lighting,
                                 track.detection_score))
        person.thumbnail_jpeg = thumbnail_jpeg or person.thumbnail_jpeg
        track.identity = Identity(person.person_id, 1.0, "confident")
        return person

    def confirm(self, person_id: str, accepted: bool, *, permanent: bool,
                consent_reference: str) -> Person:
        person = self._get(person_id)
        person.asked_to_remember = True
        if person.status == "saved":
            if permanent and not person.permanent:
                self.store.update_person(person_id, permanent=True)
                person.permanent = True
            return person
        if not accepted:
            person.status = "session" if person.name else "declined"
            return person
        if not person.name:
            raise ValueError("ask for their name first; a nameless visitor can't be saved")
        consent = Consent(how="spoken", reference=consent_reference[:300],
                          scope="permanent" if permanent else "normal")
        views = person.views[-self.cfg.max_views_per_person:]
        self.store.save_person(person_id, person.name, person.description, views, consent,
                               permanent=permanent, thumbnail_jpeg=person.thumbnail_jpeg)
        person.status, person.permanent, person.views = "saved", permanent, views
        person.thumbnail_jpeg = None
        return person

    def update(self, person_id: str, *, name: str | None = None,
               description: str | None = None, track: Track | None = None,
               lighting: str = "day") -> Person:
        person = self._get(person_id)
        if name:
            if person.status == "saved" and person.name and name != person.name:
                self.store.update_person(person_id, add_alias=person.name)
            person.name = name
        if description is not None:
            person.description = description
        if person.status == "saved":
            self.store.update_person(person_id, name=name, description=description)
        if track is not None:
            track.identity = Identity(person_id, 1.0, "confident")
            self._add_view(person, track, lighting, time.monotonic(), force=True)
        return person

    # ------------------------------------------------------------------ while people are in view

    def observe(self, tracks: list[Track], lighting: str, now: float) -> None:
        """Called for every analysed frame: last-seen times and automatic new views."""
        for track in tracks:
            person = self._identity_of(track)
            if person is None:
                continue
            person.last_seen = now
            if person.status == "saved" and now - self._last_touch.get(person.person_id, 0) > 60:
                self._last_touch[person.person_id] = now
                self.store.touch(person.person_id)
            self._maybe_add_view(person, track, lighting, now)

    def _maybe_add_view(self, person: Person, track: Track, lighting: str, now: float) -> None:
        """Once someone is recognised confidently, save how they look from new angles."""
        identity, match = track.identity, track.last_match
        if identity is None or identity.level != "confident":
            return
        if match is None or match.person_id != person.person_id:
            return  # this frame must still resemble them, so a track mix-up can't poison it
        if now - person.last_view_added < 20 or track.detection_score < 0.85:
            return
        known = {(v.angle, v.lighting) for v in person.views}
        if (track.angle, lighting) in known and match.score >= 0.6:
            return
        self._add_view(person, track, lighting, now)

    def _add_view(self, person: Person, track: Track, lighting: str, now: float,
                  force: bool = False) -> None:
        view = View(track.embedding.copy(), track.angle, lighting, track.detection_score)
        person.last_view_added = now
        if person.status == "saved":
            self.store.add_view(person.person_id, view, self.cfg.max_views_per_person)
        person.views.append(view)
        if len(person.views) > self.cfg.max_views_per_person:
            same = [v for v in person.views if (v.angle, v.lighting) == (view.angle, lighting)]
            person.views.remove((same if len(same) > 1 else person.views)[0])
        log.debug("new %s/%s view for %s%s", track.angle, lighting, person.person_id,
                  " (asked)" if force else "")

    def expire_unsaved(self, now: float) -> list[str]:
        """Drop unsaved people out of view for ~10 minutes; nothing of them was ever kept."""
        gone = [p.person_id for p in self.people.values() if p.status != "saved"
                and now - p.last_seen > self.cfg.pending_forget_after_s]
        for person_id in gone:
            del self.people[person_id]
        return gone

    # ------------------------------------------------------------------ finding and forgetting

    def find(self, name: str) -> list[Person]:
        wanted = name.strip().lower()
        return [p for p in self.people.values() if p.name and wanted in p.name.lower()]

    def forget(self, person_id: str) -> ErasureReport:
        person = self._get(person_id)
        report = self.store.erase(person_id) if person.status == "saved" else \
            ErasureReport(person_id, person.name, len(person.views), 0)
        del self.people[person_id]
        return report

    def get(self, person_id: str) -> Person | None:
        return self.people.get(person_id)

    def _get(self, person_id: str) -> Person:
        person = self.people.get(person_id)
        if person is None:
            raise KeyError(f"no person {person_id!r}")
        return person

    def _identity_of(self, track: Track) -> Person | None:
        if track.identity is None or track.identity.level == "unknown":
            return None
        return self.people.get(track.identity.person_id)

    def describe_track(self, track: Track) -> str:
        identity = track.identity
        person = self.people.get(identity.person_id) if identity else None
        if identity is None or person is None:
            return f"track {track.track_id}: unknown ({track.angle})"
        return (f"track {track.track_id}: {person.label}, {identity.score:.2f}, "
                f"{identity.level}, {track.angle})")
