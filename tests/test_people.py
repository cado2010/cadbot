# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""The people store and registry: consent gate, reboot survival, erasure, automatic views."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from cadbot.config import VisionConfig
from cadbot.people.registry import PeopleRegistry
from cadbot.people.store import Consent, ConsentRequired, PeopleStore, View
from cadbot.vision.tracker import Identity, Tracker
from tests.fakes.vision import face, identity_vector


@pytest.fixture
def store(tmp_path: Path) -> Iterator[PeopleStore]:
    s = PeopleStore(tmp_path / "cadbot.db", tmp_path / "faces")
    yield s
    s.close()


def consent() -> Consent:
    return Consent(how="spoken", reference="yes, remember me")


def view(seed: int, angle: str = "frontal", lighting: str = "day") -> View:
    return View(identity_vector(seed), angle, lighting, 0.9)


# ----------------------------------------------------------------------- store


def test_nothing_is_saved_without_consent(store: PeopleStore) -> None:
    with pytest.raises(ConsentRequired):
        store.save_person("p_1", "Sam", "", [view(1)], None)
    with pytest.raises(ConsentRequired):
        store.add_view("p_1", view(1), max_views=8)
    with pytest.raises(ConsentRequired):
        store.update_person("p_1", name="Sam")
    assert store.load_all() == []


def test_people_survive_a_restart(tmp_path: Path) -> None:
    db, faces = tmp_path / "cadbot.db", tmp_path / "faces"
    first = PeopleStore(db, faces)
    first.save_person("p_1", "Priya", "glasses", [view(1), view(1, "left")], consent(),
                      thumbnail_jpeg=b"\xff\xd8jpeg")
    first.close()
    again = PeopleStore(db, faces)
    (person,) = again.load_all()
    again.close()
    assert person.name == "Priya" and person.description == "glasses"
    assert [v.angle for v in person.views] == ["frontal", "left"]
    assert np.allclose(person.views[0].embedding, identity_vector(1))
    assert person.consent.how == "spoken" and person.consent.reference == "yes, remember me"
    assert (faces / "p_1" / "thumb.jpg").read_bytes() == b"\xff\xd8jpeg"


def test_views_are_capped(store: PeopleStore) -> None:
    store.save_person("p_1", "Sam", "", [view(1)], consent())
    for i in range(10):
        store.add_view("p_1", view(100 + i, "left"), max_views=3)
    (person,) = store.load_all()
    assert len(person.views) == 3


def test_erase_removes_everything_and_survives_backup_restore(tmp_path: Path) -> None:
    db, faces = tmp_path / "cadbot.db", tmp_path / "faces"
    store = PeopleStore(db, faces)
    store.save_person("p_1", "Raj", "", [view(1), view(2)], consent(), thumbnail_jpeg=b"x")
    report = store.erase("p_1")
    assert (report.name, report.views, report.thumbnails) == ("Raj", 2, 1)
    assert store.load_all() == [] and not (faces / "p_1").exists()
    store.close()
    # An old backup brings Raj back; the erasure is applied again on startup.
    raw = sqlite3.connect(db)
    raw.execute("INSERT INTO people (person_id, name, created_at, consent_at, consent_how, "
                "consent_scope) VALUES ('p_1', 'Raj', 'x', 'x', 'spoken', 'normal')")
    raw.commit()
    raw.close()
    store = PeopleStore(db, faces)
    assert store.load_all() == []
    store.close()


def test_erasure_record_holds_no_name(store: PeopleStore) -> None:
    store.save_person("p_1", "Raj", "", [view(1)], consent())
    store.erase("p_1")
    rows = store._db.execute("SELECT * FROM erasures").fetchall()
    assert len(rows) == 1 and "Raj" not in str(rows)


# ----------------------------------------------------------------------- registry


@pytest.fixture
def people(store: PeopleStore) -> PeopleRegistry:
    return PeopleRegistry(store, VisionConfig())


def track_for(seed: int, tracker: Tracker | None = None, **kw):  # type: ignore[no-untyped-def]
    tracker = tracker or Tracker()
    (track,), _ = tracker.update([face(seed, **kw)], 0)
    return track


def test_pending_people_are_never_written(people: PeopleRegistry, store: PeopleStore) -> None:
    person = people.remember_pending(track_for(1), name="Sam", description="red jacket",
                                     declined=False, lighting="day", thumbnail_jpeg=b"t")
    assert person.status == "pending" and store.load_all() == []
    people.confirm(person.person_id, False, permanent=False, consent_reference="no thanks")
    assert person.status == "session" and store.load_all() == []
    assert not (store.faces_dir / person.person_id).exists()


def test_yes_saves_face_name_and_consent(people: PeopleRegistry, store: PeopleStore) -> None:
    person = people.remember_pending(track_for(1), name="Sam", description="", declined=False,
                                     lighting="day", thumbnail_jpeg=b"t")
    people.confirm(person.person_id, True, permanent=True, consent_reference="yes, for good")
    (saved,) = store.load_all()
    assert saved.name == "Sam" and saved.permanent and saved.consent.scope == "permanent"
    assert saved.consent.reference == "yes, for good"
    assert store.thumbnail_path(person.person_id).exists()


def test_nameless_visitor_cannot_be_saved(people: PeopleRegistry) -> None:
    person = people.remember_pending(track_for(1), name=None, description="", declined=True,
                                     lighting="day", thumbnail_jpeg=None)
    assert person.status == "declined" and person.person_id.startswith("v_")
    with pytest.raises(ValueError):
        people.confirm(person.person_id, True, permanent=False, consent_reference="yes")


def test_match_levels(people: PeopleRegistry) -> None:
    person = people.remember_pending(track_for(1), name="Sam", description="", declined=False,
                                     lighting="day", thumbnail_jpeg=None)
    same = people.match(identity_vector(1, noise=0.3))
    assert same is not None and same.person_id == person.person_id
    assert same.level == "confident"
    assert people.match(identity_vector(2)) is None  # a stranger


def test_unsaved_people_are_dropped_after_leaving(people: PeopleRegistry) -> None:
    person = people.remember_pending(track_for(1), name="Sam", description="", declined=False,
                                     lighting="day", thumbnail_jpeg=None)
    person.last_seen = 0
    assert people.expire_unsaved(now=601) == [person.person_id]
    assert people.get(person.person_id) is None


def test_new_angles_are_learned_for_saved_people(people: PeopleRegistry,
                                                 store: PeopleStore) -> None:
    tracker = Tracker()
    track = track_for(1, tracker)
    person = people.remember_pending(track, name="Sam", description="", declined=False,
                                     lighting="day", thumbnail_jpeg=None)
    people.confirm(person.person_id, True, permanent=False, consent_reference="yes")
    # Sam turns to the left a little later; the frame still resembles them.
    (turned,), _ = tracker.update([face(1, angle="left", noise=0.4)], 30)
    turned.update_identity(people.match(turned.embedding))
    people.observe([turned], "day", now=30)
    (saved,) = store.load_all()
    assert sorted(v.angle for v in saved.views) == ["frontal", "left"]
    # the same angle again shortly after adds nothing
    people.observe([turned], "day", now=35)
    assert len(store.load_all()[0].views) == 2


def test_no_views_learned_from_a_track_that_no_longer_resembles(people: PeopleRegistry,
                                                                store: PeopleStore) -> None:
    track = track_for(1)
    person = people.remember_pending(track, name="Sam", description="", declined=False,
                                     lighting="day", thumbnail_jpeg=None)
    people.confirm(person.person_id, True, permanent=False, consent_reference="yes")
    track.angle, track.embedding = "right", identity_vector(99)  # tracker mix-up
    track.update_identity(people.match(track.embedding))
    track.identity = Identity(person.person_id, 0.9, "confident")
    people.observe([track], "night", now=100)
    assert len(store.load_all()[0].views) == 1


def test_forget_and_find(people: PeopleRegistry, store: PeopleStore) -> None:
    person = people.remember_pending(track_for(1), name="Priya", description="", declined=False,
                                     lighting="day", thumbnail_jpeg=None)
    people.confirm(person.person_id, True, permanent=False, consent_reference="yes")
    assert [p.person_id for p in people.find("pri")] == [person.person_id]
    people.forget(person.person_id)
    assert people.find("priya") == [] and store.load_all() == []


# ----------------------------------------------------------------------- admin command


def test_admin_lists_and_forgets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                 capsys: pytest.CaptureFixture[str]) -> None:
    from cadbot.admin.__main__ import main as admin

    monkeypatch.setattr("cadbot.admin.__main__.open_store",
                        lambda: PeopleStore(tmp_path / "cadbot.db", tmp_path / "faces"))
    store = PeopleStore(tmp_path / "cadbot.db", tmp_path / "faces")
    store.save_person("p_1", "Raj", "", [view(1)], consent())
    store.save_person("p_2", "Rajesh", "", [view(2)], consent())
    store.close()
    assert admin(["people"]) == 0
    assert "Raj" in capsys.readouterr().out
    assert admin(["forget", "--name", "raj", "--yes"]) == 1  # two matches: needs --id
    assert admin(["forget", "--id", "p_1", "--yes"]) == 0
    assert "Erased Raj" in capsys.readouterr().out
    check = PeopleStore(tmp_path / "cadbot.db", tmp_path / "faces")
    assert [p.name for p in check.load_all()] == ["Rajesh"]
    check.close()
