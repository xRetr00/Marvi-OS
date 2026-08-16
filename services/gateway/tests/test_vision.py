"""Face recognition, visitor queueing, and homecoming reports.

No camera and no model here: the logic that decides who is a stranger, how
often a lingering stranger is recorded, and when the owner hears about it is
all testable from embeddings alone.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from marvi_gateway.initiative import Initiative
from marvi_gateway.journal import EventJournal
from marvi_gateway.memory import MemoryStore
from marvi_gateway.mind import Mind
from marvi_gateway.vision import (
    KNOWN_THRESHOLD,
    FaceLibrary,
    VisionService,
    cosine,
    frame_motion,
)

OWNER = [1.0, 0.0, 0.0, 0.0]
OWNER_TILTED = [0.95, 0.30, 0.0, 0.0]  # same person, worse angle
FRIEND = [0.0, 1.0, 0.0, 0.0]
STRANGER = [0.0, 0.0, 1.0, 0.0]
OTHER_STRANGER = [0.0, 0.0, 0.0, 1.0]


@pytest.fixture
def faces(tmp_path):
    library = FaceLibrary(tmp_path / "vision")
    yield library
    library.close()


# -- matching ---------------------------------------------------------------


def test_cosine_is_sane() -> None:
    assert cosine(OWNER, OWNER) == pytest.approx(1.0)
    assert cosine(OWNER, FRIEND) == pytest.approx(0.0)
    assert cosine([], OWNER) == 0.0
    assert cosine([1.0], OWNER) == 0.0  # mismatched length is not a match


def test_the_owner_is_recognised_as_the_owner(faces) -> None:
    faces.enroll("Shereef", [OWNER], owner=True)
    verdict = faces.match(OWNER)

    assert verdict["status"] == "owner"
    assert verdict["identity"] == "Shereef"


def test_a_bad_angle_on_the_owner_is_not_a_stranger(faces) -> None:
    faces.enroll("Shereef", [OWNER], owner=True)
    verdict = faces.match(OWNER_TILTED)

    # This is the failure mode that would otherwise manufacture visitors.
    assert verdict["status"] == "owner"


def test_a_known_person_is_not_the_owner(faces) -> None:
    faces.enroll("Shereef", [OWNER], owner=True)
    faces.enroll("Alex", [FRIEND])
    verdict = faces.match(FRIEND)

    assert verdict["status"] == "known"
    assert verdict["identity"] == "Alex"


def test_an_unfamiliar_face_is_unknown(faces) -> None:
    faces.enroll("Shereef", [OWNER], owner=True)
    verdict = faces.match(STRANGER)

    assert verdict["status"] == "unknown"
    assert verdict["score"] < KNOWN_THRESHOLD


def test_there_is_only_ever_one_owner(faces) -> None:
    faces.enroll("Shereef", [OWNER], owner=True)
    faces.enroll("Someone Else", [FRIEND], owner=True)

    owners = [p for p in faces.people() if p["owner"]]
    assert len(owners) == 1
    assert owners[0]["name"] == "Someone Else"


def test_a_person_needs_a_name_and_a_sample(faces) -> None:
    with pytest.raises(ValueError, match="name"):
        faces.enroll("  ", [OWNER])
    with pytest.raises(ValueError, match="sample"):
        faces.enroll("Nobody", [])


def test_forgetting_a_person_removes_their_face(faces) -> None:
    faces.enroll("Alex", [FRIEND])
    assert faces.forget_person("alex") is True
    assert faces.match(FRIEND)["status"] == "unknown"


# -- visitor queue ----------------------------------------------------------


def test_a_lingering_stranger_is_one_entry_not_fifty(faces) -> None:
    faces.enroll("Shereef", [OWNER], owner=True)
    first = faces.record_sighting("unknown", "unknown", 0.1, "a.jpg", STRANGER)
    again = faces.record_sighting("unknown", "unknown", 0.1, "b.jpg", STRANGER)

    assert first is not None
    assert again is None
    assert len(faces.unreported_visitors()) == 1


def test_two_different_strangers_are_two_entries(faces) -> None:
    faces.record_sighting("unknown", "unknown", 0.1, "a.jpg", STRANGER)
    faces.record_sighting("unknown", "unknown", 0.1, "b.jpg", OTHER_STRANGER)

    assert len(faces.unreported_visitors()) == 2


def test_seeing_the_owner_never_queues_a_visitor(faces) -> None:
    faces.enroll("Shereef", [OWNER], owner=True)
    faces.record_sighting("Shereef", "owner", 0.99, None, OWNER)

    assert faces.unreported_visitors() == []


def test_a_visitor_entry_carries_a_face_a_date_and_a_time(faces) -> None:
    faces.record_sighting(
        "unknown", "unknown", 0.1, "c:/faces/x.jpg", STRANGER,
        now=datetime(2026, 8, 17, 14, 30, 5, tzinfo=UTC),
    )
    visitor = faces.unreported_visitors()[0]

    assert visitor["thumbnail"] == "c:/faces/x.jpg"
    assert visitor["date"] == "2026-08-17"
    assert visitor["time"] == "14:30:05"


def test_reporting_clears_the_queue(faces) -> None:
    faces.record_sighting("unknown", "unknown", 0.1, None, STRANGER)
    assert faces.mark_reported() == 1
    assert faces.unreported_visitors() == []


# -- approval ---------------------------------------------------------------


def test_approving_a_stranger_teaches_marvi_the_face(faces) -> None:
    sighting = faces.record_sighting("unknown", "unknown", 0.1, None, STRANGER)
    faces.approve(sighting, "Delivery driver")

    # Recognised from now on, and no longer waiting to be reported.
    assert faces.match(STRANGER)["identity"] == "Delivery driver"
    assert faces.unreported_visitors() == []


def test_a_stranger_can_be_approved_as_the_owner(faces) -> None:
    sighting = faces.record_sighting("unknown", "unknown", 0.1, None, STRANGER)
    faces.approve(sighting, "Shereef", owner=True)

    assert faces.match(STRANGER)["status"] == "owner"


def test_rejecting_a_sighting_discards_it(faces) -> None:
    sighting = faces.record_sighting("unknown", "unknown", 0.1, None, STRANGER)
    assert faces.reject(sighting) is True
    assert faces.unreported_visitors() == []
    assert faces.match(STRANGER)["status"] == "unknown"


def test_approving_something_with_no_stored_face_is_refused(faces) -> None:
    with pytest.raises(ValueError, match="no stored face"):
        faces.approve(999, "Nobody")


# -- motion gate ------------------------------------------------------------


def test_motion_gate_measures_change() -> None:
    import numpy as np

    still = np.zeros((120, 160), dtype="uint8")
    assert frame_motion(still, still) == 0.0
    assert frame_motion(None, still) == 100.0  # first frame always analysed
    assert frame_motion(still, np.full((120, 160), 200, dtype="uint8")) > 100.0
    # A resolution change must not be read as stillness.
    assert frame_motion(still, np.zeros((60, 80), dtype="uint8")) == 100.0


def test_vision_is_off_unless_asked_for(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MARVI_VISION", raising=False)
    service = VisionService(library=FaceLibrary(tmp_path / "v"))
    assert service.available() is False
    monkeypatch.setenv("MARVI_VISION", "1")
    assert service.available() is True


def test_a_missing_camera_is_reported_not_raised(tmp_path) -> None:
    service = VisionService(library=FaceLibrary(tmp_path / "v"), camera_index=999)
    result = service.observe(seconds=0.5)

    assert result["ok"] is False
    assert "unavailable" in result["error"]


# -- homecoming -------------------------------------------------------------


@pytest.fixture
def stack(tmp_path):
    journal = EventJournal(tmp_path / "journal.sqlite3")
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    library = FaceLibrary(tmp_path / "vision")
    mind = Mind(journal, memory=memory)
    yield journal, library, mind
    library.close()
    memory.close()
    journal.close()


def test_visitors_are_not_announced_while_the_owner_is_out(stack) -> None:
    journal, library, mind = stack
    library.record_sighting("unknown", "unknown", 0.1, "a.jpg", STRANGER)
    initiative = Initiative(mind, journal, faces=library)
    initiative._was_home = False

    assert initiative.run_homecoming(present=False)["reported"] == []
    assert journal.count_pending() == 0
    assert len(library.unreported_visitors()) == 1


def test_arriving_home_reports_the_visitors(stack) -> None:
    journal, library, mind = stack
    library.record_sighting(
        "unknown", "unknown", 0.1, "a.jpg", STRANGER,
        now=datetime(2026, 8, 17, 14, 30, tzinfo=UTC),
    )
    initiative = Initiative(mind, journal, faces=library)
    initiative._was_home = False

    result = initiative.run_homecoming(present=True)

    assert result["reported"]
    assert "1 unrecognised person" in result["summary"]
    assert "14:30" in result["summary"]
    event = journal.pending()[0]
    assert event["source"] == "vision"
    assert event["payload"]["thumbnails"] == ["a.jpg"]


def test_a_visitor_report_is_allowed_to_be_spoken(stack) -> None:
    journal, library, mind = stack
    library.record_sighting("unknown", "unknown", 0.1, "a.jpg", STRANGER)
    initiative = Initiative(mind, journal, faces=library)
    initiative._was_home = False
    initiative.run_homecoming(present=True)

    result = mind.tick()

    assert result["decisions"][0]["surface"] == "speak"


def test_staying_home_does_not_re_report(stack) -> None:
    journal, library, mind = stack
    library.record_sighting("unknown", "unknown", 0.1, "a.jpg", STRANGER)
    initiative = Initiative(mind, journal, faces=library)
    initiative._was_home = False
    initiative.run_homecoming(present=True)
    second = initiative.run_homecoming(present=True)

    # Only the arrival edge reports; sitting at home does not repeat it.
    assert second["reported"] == []


def test_nothing_to_report_is_silent(stack) -> None:
    journal, library, mind = stack
    initiative = Initiative(mind, journal, faces=library)
    initiative._was_home = False

    assert initiative.run_homecoming(present=True)["reported"] == []
    assert journal.count_pending() == 0
