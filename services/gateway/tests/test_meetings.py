"""Taking notes in a meeting, and the rules about when Marvi may not.

The recording path is exercised for real where the machine allows it: a tone
played to the speakers and captured back is the only way to know the loopback
stream is the loopback stream and not four seconds of silence. Everything about
*consent* and *what starts a recording* is tested without any audio at all,
because those are the parts that must hold on every machine.
"""

from __future__ import annotations

import os
import wave
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from marvi_gateway import audiocapture
from marvi_gateway.meetings import (
    SILENCE_PEAK,
    WINDOW_SECONDS,
    ConsentNeededError,
    Meetings,
    due,
    windows,
)


def _store(tmp_path) -> Meetings:
    return Meetings(tmp_path / "meetings.db", tmp_path / "recordings")


def test_nothing_is_recorded_until_the_notice_has_been_accepted(tmp_path) -> None:
    """The first rule. Marvi can offer; she cannot begin."""
    store = _store(tmp_path)

    assert store.consent()["accepted"] is False
    with pytest.raises(ConsentNeededError):
        store.start("Standup")

    accepted = store.accept_consent()
    assert accepted["accepted"] is True and accepted["accepted_at"]


def test_the_notice_says_what_recording_other_people_means(tmp_path) -> None:
    notice = _store(tmp_path).consent()["notice"]

    assert "the other people" in notice
    assert "agreement" in notice
    # And what Marvi does, so accepting is informed rather than ritual.
    assert "indicator" in notice and "on this machine" in notice


def test_the_indicator_always_answers(tmp_path) -> None:
    """A window that cannot tell whether it is recording draws nothing, and
    "nothing" is indistinguishable from "not recording"."""
    assert _store(tmp_path).now() == {"recording": False}


def test_a_restart_corrects_a_meeting_that_says_it_is_recording(tmp_path) -> None:
    """The one direction where a stale state is a lie that matters."""
    store = _store(tmp_path)
    store.accept_consent()
    store._db.execute(
        "INSERT INTO meetings (id, title, state, started_at) VALUES ('x', 'Long call',"
        " 'recording', '2026-09-18T10:00:00+00:00')"
    )
    store._db.commit()

    assert store.recover() == 1
    after = store.get("x")
    assert after["state"] == "failed"
    assert "restarted" in after["detail"]
    assert store.now() == {"recording": False}


def test_silence_is_not_transcribed(tmp_path) -> None:
    """One side of a call is quiet for most of it, and that quiet is most of
    what transcribing the whole thing would cost."""
    path = tmp_path / "side.wav"
    quiet = (0).to_bytes(2, "little", signed=True) * audiocapture.TARGET_RATE * WINDOW_SECONDS
    loud = (SILENCE_PEAK * 4).to_bytes(2, "little", signed=True) * audiocapture.TARGET_RATE
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(audiocapture.TARGET_RATE)
        handle.writeframes(quiet + loud)

    cut = windows(path)

    assert [at for at, _ in cut] == [WINDOW_SECONDS], "only the window with something in it"


def test_the_two_sides_are_interleaved_by_when_they_happened(tmp_path) -> None:
    """Speaker turns without diarisation: which stream it arrived on is the
    speaker, and that is exact rather than inferred."""
    store = _store(tmp_path)
    store.accept_consent()
    folder = tmp_path / "one"
    folder.mkdir()
    for name in ("mic.wav", "speakers.wav"):
        with wave.open(str(folder / name), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(audiocapture.TARGET_RATE)
            handle.writeframes(
                (SILENCE_PEAK * 4).to_bytes(2, "little", signed=True)
                * audiocapture.TARGET_RATE * WINDOW_SECONDS * 2
            )
    heard = iter(["you first", "you second", "them first", "them second"])
    store.transcribe = lambda pcm: next(heard)

    turns = store._turns(folder)

    assert [(at, who) for at, who, _ in turns] == [
        (0, "them"), (0, "you"), (WINDOW_SECONDS, "them"), (WINDOW_SECONDS, "you")
    ]


def test_what_the_model_said_is_read_back_or_ignored() -> None:
    """A meeting with no usable summary is still a meeting with a transcript,
    so a model that answers with prose rather than JSON costs nothing."""
    from marvi_gateway.meetings import _parsed

    summary, decisions, actions = _parsed(
        '```json\n{"summary": "They picked Tuesday.", "decisions": ["Ship on Tuesday"],'
        ' "actions": ["Sam to update the changelog"]}\n```'
    )
    assert summary == "They picked Tuesday."
    assert decisions == ["Ship on Tuesday"] and actions == ["Sam to update the changelog"]

    assert _parsed("I could not read that transcript.") == ("", [], [])
    assert _parsed("") == ("", [], [])


def test_only_a_meeting_worth_offering_is_offered() -> None:
    """An offer for every calendar entry is an offer nobody reads."""
    soon = datetime.now(UTC) + timedelta(seconds=30)
    later = datetime.now(UTC) + timedelta(hours=3)
    events = [
        {"id": "a", "title": "Lunch", "start": soon.isoformat(), "all_day": False},
        {"id": "b", "title": "Sync", "location": "https://meet.google.com/abc",
         "start": soon.isoformat(), "all_day": False},
        {"id": "c", "title": "Retro https://zoom.us/j/1", "start": later.isoformat(),
         "all_day": False},
        {"id": "d", "title": "Leave https://zoom.us/j/2", "start": soon.isoformat(),
         "all_day": True},
    ]

    offered = due(events)

    assert offered is not None and offered["id"] == "b", "a link, and starting now"
    assert due([events[0]]) is None, "no link, so nothing to listen to"
    assert due([events[2]]) is None, "hours away"
    assert due([events[3]]) is None, "a whole day is not a meeting"


def test_action_items_become_cards(tmp_path) -> None:
    """A list of things somebody owes, kept where nobody looks again, is a list
    that may as well not exist."""
    from marvi_gateway.jobs import JobsStore

    store = _store(tmp_path)
    store.board = JobsStore(tmp_path / "jobs.db")
    store.accept_consent()
    store._db.execute(
        "INSERT INTO meetings (id, title, state, started_at) VALUES ('m', 'Planning', 'ready', 'x')"
    )
    store._db.commit()

    store._file_actions("m", ["Sam to update the changelog", "Book the room"])

    titles = [card["title"] for card in store.board.board()["columns"]["todo"]]
    assert sorted(titles) == ["Book the room", "Sam to update the changelog"]
    assert "Planning" in store.board.board()["columns"]["todo"][0]["body"]


def test_forgetting_a_meeting_takes_the_recording_with_it(tmp_path) -> None:
    """There is no bin for this. An hour of a room is not something to keep
    after somebody has asked for it to go."""
    store = _store(tmp_path)
    store.accept_consent()
    folder = store.folder / "m"
    folder.mkdir(parents=True)
    (folder / "mic.wav").write_bytes(b"not really audio")
    store._db.execute(
        "INSERT INTO meetings (id, title, state, started_at, folder) VALUES"
        " ('m', 'Planning', 'ready', 'x', ?)", (str(folder),)
    )
    store._db.commit()

    assert store.remove("m") is True
    assert not folder.exists()
    assert store.remove("m") is False


@pytest.mark.asyncio
async def test_the_routes_refuse_before_the_notice_and_allow_after(monkeypatch, tmp_path) -> None:
    from marvi_gateway.app import create_app

    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        listed = await client.get("/meetings")
        assert listed.json()["consent"]["accepted"] is False
        assert listed.json()["now"] == {"recording": False}

        # 428: the request is fine, something has to happen first.
        refused = await client.post("/meetings", json={"title": "Standup"})
        assert refused.status_code == 428

        assert (await client.post("/meetings/consent")).json()["accepted"] is True
        assert (await client.get("/meetings/nope")).status_code == 404
        # Nothing is recording, so stopping is a 409 rather than a silent ok.
        assert (await client.post("/meetings/nope/stop")).status_code == 409


@pytest.mark.skipif(os.name != "nt", reason="WASAPI loopback is Windows")
def test_the_speakers_and_the_microphone_are_both_really_recorded(tmp_path) -> None:
    """The one thing no mock can tell you: that the loopback stream carries
    what the speakers are playing.

    A 440 Hz tone is played and the captured audio is checked for 440 Hz. A
    stream that silently records nothing, or records the microphone twice,
    fails this and passes anything written against a fake.
    """
    numpy = pytest.importorskip("numpy")
    import math
    import struct
    import subprocess
    import time

    can, why = audiocapture.available()
    if not can:
        pytest.skip(why)

    tone = tmp_path / "tone.wav"
    with wave.open(str(tone), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(44_100)
        handle.writeframes(b"".join(
            struct.pack("<h", int(9000 * math.sin(2 * math.pi * 440 * n / 44_100)))
            for n in range(44_100 * 3)
        ))

    heard = bytearray()
    capture = audiocapture.Capture(True, heard.extend)
    try:
        capture.start()
    except audiocapture.CaptureUnavailableError as exc:
        pytest.skip(str(exc))
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f'(New-Object System.Media.SoundPlayer "{tone}").PlaySync()'],
            check=False, timeout=30, capture_output=True,
        )
        time.sleep(0.3)
    finally:
        capture.stop()

    samples = numpy.frombuffer(bytes(heard), dtype=numpy.int16).astype(float)
    assert samples.size > audiocapture.TARGET_RATE, "less than a second came back"
    middle = samples[audiocapture.TARGET_RATE // 2 : audiocapture.TARGET_RATE * 2]
    spectrum = numpy.abs(numpy.fft.rfft(middle))
    loudest = numpy.fft.rfftfreq(middle.size, 1 / audiocapture.TARGET_RATE)[spectrum.argmax()]
    assert 430 < loudest < 450, f"the loopback heard {loudest:.0f} Hz, not the tone"
