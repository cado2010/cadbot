# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""The people store: SQLite (WAL) plus face thumbnails on disk. Survives reboots.

Enforced in code, whatever Claude asks: nothing about a person is written unless their
consent is recorded. Pending and declined people never reach this module. Erasing a person
removes every row and file in one step, then checks nothing is left.
"""

from __future__ import annotations

import logging
import secrets
import shutil
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    person_id     TEXT PRIMARY KEY,
    name          TEXT,
    aliases       TEXT NOT NULL DEFAULT '',
    description   TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    last_seen     TEXT,
    permanent     INTEGER NOT NULL DEFAULT 0,
    consent_at    TEXT NOT NULL,
    consent_how   TEXT NOT NULL,
    consent_ref   TEXT NOT NULL DEFAULT '',
    consent_scope TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS embeddings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id  TEXT NOT NULL REFERENCES people(person_id) ON DELETE CASCADE,
    vector     BLOB NOT NULL,
    angle      TEXT NOT NULL,
    lighting   TEXT NOT NULL,
    quality    REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS embeddings_person ON embeddings(person_id);
CREATE TABLE IF NOT EXISTS erasures (
    erasure_id TEXT PRIMARY KEY,
    person_id  TEXT NOT NULL,
    erased_at  TEXT NOT NULL
);
"""


class ConsentRequired(PermissionError):
    """Raised when something tries to store data about a person without their consent."""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Consent:
    """A person's clear yes to being remembered."""

    how: str  # "spoken" (or "web ui" / "admin" in later milestones)
    reference: str  # what they said, so the record shows how consent was given
    scope: str = "normal"  # "normal" or "permanent"
    at: str = field(default_factory=now_iso)


@dataclass
class View:
    """One saved face embedding, tagged with its angle and lighting."""

    embedding: np.ndarray
    angle: str
    lighting: str  # "day" or "night"
    quality: float = 0.0
    created_at: str = field(default_factory=now_iso)


@dataclass
class StoredPerson:
    person_id: str
    name: str | None
    description: str
    permanent: bool
    created_at: str
    last_seen: str | None
    views: list[View]
    consent: Consent
    aliases: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ErasureReport:
    person_id: str
    name: str | None
    views: int
    thumbnails: int


def new_person_id() -> str:
    return "p_" + secrets.token_hex(4)


class PeopleStore:
    def __init__(self, db_path: Path, faces_dir: Path) -> None:
        self.db_path = db_path
        self.faces_dir = faces_dir
        db_path.parent.mkdir(parents=True, exist_ok=True)
        faces_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(SCHEMA)
        self.reapply_erasures()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ------------------------------------------------------------------ reading

    def load_all(self) -> list[StoredPerson]:
        with self._lock:
            people = self._db.execute(
                "SELECT person_id, name, description, permanent, created_at, last_seen, "
                "consent_how, consent_ref, consent_scope, consent_at, aliases FROM people"
            ).fetchall()
            views = self._db.execute(
                "SELECT person_id, vector, angle, lighting, quality, created_at "
                "FROM embeddings ORDER BY id").fetchall()
        by_person: dict[str, list[View]] = {}
        for pid, blob, angle, lighting, quality, created in views:
            vector = np.frombuffer(blob, dtype=np.float32).copy()
            by_person.setdefault(pid, []).append(View(vector, angle, lighting, quality, created))
        return [StoredPerson(
            person_id=pid, name=name, description=desc, permanent=bool(perm), created_at=created,
            last_seen=seen, views=by_person.get(pid, []),
            consent=Consent(how=how, reference=ref, scope=scope, at=at),
            aliases=[a for a in aliases.split("|") if a])
            for pid, name, desc, perm, created, seen, how, ref, scope, at, aliases in people]

    def exists(self, person_id: str) -> bool:
        with self._lock:
            row = self._db.execute("SELECT 1 FROM people WHERE person_id = ?",
                                   (person_id,)).fetchone()
        return row is not None

    def thumbnail_path(self, person_id: str) -> Path:
        return self.faces_dir / person_id / "thumb.jpg"

    # ------------------------------------------------------------------ writing (consent-gated)

    def save_person(self, person_id: str, name: str | None, description: str,
                    views: list[View], consent: Consent | None, *, permanent: bool = False,
                    thumbnail_jpeg: bytes | None = None) -> None:
        """Save a person who has agreed to be remembered. Refuses without consent."""
        if consent is None or not consent.how or not consent.at:
            raise ConsentRequired(f"no consent recorded for {person_id}; nothing saved")
        with self._lock, self._db:
            self._db.execute("BEGIN")
            self._db.execute(
                "INSERT INTO people (person_id, name, description, created_at, last_seen, "
                "permanent, consent_at, consent_how, consent_ref, consent_scope) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (person_id, name, description, now_iso(), now_iso(), int(permanent),
                 consent.at, consent.how, consent.reference, consent.scope))
            for view in views:
                self._insert_view(person_id, view)
        if thumbnail_jpeg:
            self._write_thumbnail(person_id, thumbnail_jpeg)
        log.info("saved person %s with %d view(s)", person_id, len(views))

    def add_view(self, person_id: str, view: View, max_views: int) -> None:
        """Add a face view to a consented person, replacing an old one when full."""
        with self._lock, self._db:
            if self._db.execute("SELECT 1 FROM people WHERE person_id = ?",
                                (person_id,)).fetchone() is None:
                raise ConsentRequired(f"{person_id} is not a saved person; view not stored")
            self._db.execute("BEGIN")
            rows = self._db.execute(
                "SELECT id, angle, lighting FROM embeddings WHERE person_id = ? ORDER BY id",
                (person_id,)).fetchall()
            if len(rows) >= max_views:
                same = [r for r in rows if r[1] == view.angle and r[2] == view.lighting]
                victim = (same or rows)[0][0]  # oldest of the same kind, else the oldest
                self._db.execute("DELETE FROM embeddings WHERE id = ?", (victim,))
            self._insert_view(person_id, view)

    def update_person(self, person_id: str, *, name: str | None = None,
                      description: str | None = None, permanent: bool | None = None,
                      add_alias: str | None = None) -> None:
        if not self.exists(person_id):
            raise ConsentRequired(f"{person_id} is not a saved person; nothing updated")
        with self._lock:
            if name is not None:
                self._db.execute("UPDATE people SET name = ? WHERE person_id = ?",
                                 (name, person_id))
            if description is not None:
                self._db.execute("UPDATE people SET description = ? WHERE person_id = ?",
                                 (description, person_id))
            if permanent is not None:
                self._db.execute(
                    "UPDATE people SET permanent = ?, consent_scope = ? WHERE person_id = ?",
                    (int(permanent), "permanent" if permanent else "normal", person_id))
            if add_alias:
                row = self._db.execute("SELECT aliases FROM people WHERE person_id = ?",
                                       (person_id,)).fetchone()
                aliases = {a for a in row[0].split("|") if a} | {add_alias}
                self._db.execute("UPDATE people SET aliases = ? WHERE person_id = ?",
                                 ("|".join(sorted(aliases)), person_id))

    def touch(self, person_id: str) -> None:
        with self._lock:
            self._db.execute("UPDATE people SET last_seen = ? WHERE person_id = ?",
                             (now_iso(), person_id))

    def _insert_view(self, person_id: str, view: View) -> None:
        vector = np.asarray(view.embedding, dtype=np.float32).tobytes()
        self._db.execute(
            "INSERT INTO embeddings (person_id, vector, angle, lighting, quality, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (person_id, vector, view.angle, view.lighting, view.quality, view.created_at))

    def _write_thumbnail(self, person_id: str, jpeg: bytes) -> None:
        """Write to a temporary name, then rename: a half-written file never replaces one."""
        path = self.thumbnail_path(person_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(jpeg)
        tmp.replace(path)

    # ------------------------------------------------------------------ erasing

    def erase(self, person_id: str) -> ErasureReport:
        """Delete everything about a person, record the erasure, and verify it's all gone."""
        with self._lock, self._db:
            row = self._db.execute("SELECT name FROM people WHERE person_id = ?",
                                   (person_id,)).fetchone()
            views = self._db.execute("SELECT COUNT(*) FROM embeddings WHERE person_id = ?",
                                     (person_id,)).fetchone()[0]
            self._db.execute("BEGIN")
            self._db.execute("DELETE FROM embeddings WHERE person_id = ?", (person_id,))
            self._db.execute("DELETE FROM people WHERE person_id = ?", (person_id,))
            self._db.execute("INSERT INTO erasures (erasure_id, person_id, erased_at) "
                             "VALUES (?, ?, ?)", ("e_" + secrets.token_hex(6), person_id,
                                                  now_iso()))
        folder = self.faces_dir / person_id
        thumbs = len(list(folder.glob("*"))) if folder.exists() else 0
        shutil.rmtree(folder, ignore_errors=True)
        self._verify_erased(person_id)
        log.info("erased person %s", person_id)
        return ErasureReport(person_id, row[0] if row else None, views, thumbs)

    def _verify_erased(self, person_id: str) -> None:
        with self._lock:
            left = sum(self._db.execute(f"SELECT COUNT(*) FROM {table} WHERE person_id = ?",
                                        (person_id,)).fetchone()[0]
                       for table in ("people", "embeddings"))
        if left or (self.faces_dir / person_id).exists():
            raise RuntimeError(f"erasure of {person_id} incomplete: {left} row(s) remain")

    def reapply_erasures(self) -> int:
        """If an older backup was restored, erase again everyone erased since."""
        with self._lock:
            ids = [r[0] for r in self._db.execute(
                "SELECT e.person_id FROM erasures e JOIN people p USING (person_id)")]
        for person_id in ids:
            log.warning("re-applying erasure of %s (restored from an older backup?)", person_id)
            self.erase(person_id)
        return len(ids)

    def integrity_ok(self) -> bool:
        with self._lock:
            return self._db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
