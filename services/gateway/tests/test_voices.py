"""Listing the installed voices.

The naming convention is the whole feature: `en-Carter_man` is a language, a
name and a gender, and parsing it is what turns a directory of filenames into
something you can pick from.
"""

from __future__ import annotations

import pathlib

import pytest

from marvi_gateway import voices


@pytest.fixture
def voice_dir(tmp_path, monkeypatch):
    directory = tmp_path / "voices"
    directory.mkdir()
    monkeypatch.setattr(voices, "voices_dir", lambda: directory)
    return directory


def test_every_voice_is_named_for_a_person_and_a_place() -> None:
    """The picker shows these, so they have to read as choices rather than as
    identifiers: Michael, English (American), man."""
    found = voices.installed()

    assert found, "the list is part of the model and can never be empty"
    for voice in found:
        assert voice.name and voice.name[0].isupper()
        assert "English" in voice.language
        assert voice.gender in ("man", "woman")


def test_the_id_is_what_the_setting_takes() -> None:
    """What the picker writes has to be what the engine accepts."""
    ids = {voice.id for voice in voices.installed()}

    assert "am_michael" in ids
    assert all(id_.startswith(("a", "b")) for id_ in ids)


def test_there_is_no_such_thing_as_no_voices_now() -> None:
    """The engine changed and this state went with it.

    VibeVoice took speaker prompts off disk, so a fresh install had none until
    a multi-gigabyte download finished, and every caller had to handle "none
    installed". Kokoro's voices are part of an 82M checkpoint.
    """
    assert len(voices.installed()) >= 10


def test_a_voice_left_over_from_the_old_engine_is_reported_missing(monkeypatch) -> None:
    """Every install that ran Marvi before carries one.

    `en-Carter_man` was a VibeVoice speaker prompt and Kokoro has never heard
    of it. It must read as a choice that no longer exists, so the UI offers a
    new one, rather than as a voice that is merely not downloaded yet.
    """
    monkeypatch.setenv(voices.VOICE_ENV, "en-Carter_man")

    assert voices.selected() == "en-Carter_man"
    assert voices.selected() not in {v.id for v in voices.installed()}


def test_a_current_choice_is_not_reported_missing(monkeypatch) -> None:
    monkeypatch.setenv(voices.VOICE_ENV, "bf_emma")

    assert voices.selected() in {v.id for v in voices.installed()}


def test_the_shipped_model_is_found() -> None:
    """Armed means both switched on and the model actually present.

    A missing model leaves Marvi answering every turn rather than deaf, so
    "enabled but not armed" is a real state and the UI has to be able to say
    so.
    """
    from marvi_gateway import wake

    status = wake.status()

    assert status["model_present"] is True, status["model"]
    assert status["armed"] is True


def test_a_detection_is_recorded_and_then_goes_stale() -> None:
    from marvi_gateway import wake

    wake.forget()
    assert wake.status()["recently_heard"] is False

    wake.heard(0.91)
    fresh = wake.status()

    assert fresh["recently_heard"] is True
    assert fresh["confidence"] == 0.91
    assert fresh["heard_seconds_ago"] < 1
    wake.forget()


def test_turning_it_off_is_reported(monkeypatch) -> None:
    from marvi_gateway import wake

    monkeypatch.setenv("MARVI_WAKE_WORD", "false")

    status = wake.status()

    assert status["enabled"] is False
    assert status["armed"] is False


def test_the_gateway_and_the_wake_listener_agree_on_the_threshold() -> None:
    """Duplicated, because they run in different Python environments.

    The Gateway reports the sensitivity and the listener acts on it. If they
    disagree the screen shows a number that is not the one deciding whether
    Marvi answers to her name.
    """
    import re

    from marvi_gateway import wake

    source = (
        pathlib.Path(__file__).resolve().parents[2]
        / "agent"
        / "src"
        / "marvi_agent"
        / "wake_daemon.py"
    ).read_text(encoding="utf-8")

    threshold = re.search(r"DEFAULT_THRESHOLD = ([\d.]+)", source)

    assert threshold and float(threshold.group(1)) == wake.DEFAULT_THRESHOLD
