"""Listing the installed voices.

The naming convention is the whole feature: `en-Carter_man` is a language, a
name and a gender, and parsing it is what turns a directory of filenames into
something you can pick from.
"""

from __future__ import annotations

import pytest

from marvi_gateway import voices


@pytest.fixture
def voice_dir(tmp_path, monkeypatch):
    directory = tmp_path / "voices"
    directory.mkdir()
    monkeypatch.setattr(voices, "voices_dir", lambda: directory)
    return directory


def test_a_name_becomes_a_language_a_person_and_a_gender(voice_dir) -> None:
    (voice_dir / "en-Carter_man.pt").touch()

    (voice,) = voices.installed()

    assert voice.id == "en-Carter_man"
    assert voice.name == "Carter"
    assert voice.language == "English"
    assert voice.gender == "man"


def test_the_id_is_what_the_setting_takes() -> None:
    """Not the filename and not the display name -- the stem, exactly."""
    assert voices._parse("jp-Spk1_woman").id == "jp-Spk1_woman"


def test_an_unknown_language_shows_as_itself(voice_dir) -> None:
    """A voice must be selectable whether or not the table knows its language."""
    (voice_dir / "xx-Someone_woman.pt").touch()

    (voice,) = voices.installed()

    assert voice.language == "xx"
    assert voice.name == "Someone"


def test_a_name_that_breaks_the_convention_is_still_offered(voice_dir) -> None:
    """It is installed and speakable, so hiding it helps nobody."""
    (voice_dir / "custom.pt").touch()

    (voice,) = voices.installed()

    assert voice.id == "custom"
    assert voice.name == "custom"


def test_no_voices_installed_is_an_answer_not_an_error(voice_dir) -> None:
    """A fresh install has none: the TTS model is a multi-gigabyte download."""
    assert voices.installed() == []


def test_a_missing_directory_does_not_raise(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(voices, "voices_dir", lambda: tmp_path / "absent")

    assert voices.installed() == []


def test_a_chosen_voice_that_was_deleted_is_reported_missing(voice_dir, monkeypatch) -> None:
    """Rather than silently corrected. The choice happened; the file did not."""
    from fastapi.testclient import TestClient

    from marvi_gateway.app import create_app

    (voice_dir / "en-Carter_man.pt").touch()
    monkeypatch.setenv(voices.VOICE_ENV, "en-Gone_woman")

    with TestClient(create_app()) as client:
        body = client.get("/voices").json()

    assert body["missing"] is True
    assert body["selected"] == "en-Gone_woman"
    assert [row["id"] for row in body["voices"]] == ["en-Carter_man"]


def test_an_installed_choice_is_not_reported_missing(voice_dir, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from marvi_gateway.app import create_app

    (voice_dir / "en-Carter_man.pt").touch()
    monkeypatch.setenv(voices.VOICE_ENV, "en-Carter_man")

    with TestClient(create_app()) as client:
        body = client.get("/voices").json()

    assert body["missing"] is False
