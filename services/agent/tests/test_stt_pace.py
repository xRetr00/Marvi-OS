"""The two settings that decide how soon a word reaches the screen.

The chunk was a constant for as long as this recogniser has shipped, with a
comment saying the lookahead was "the dial that matters". True of accuracy and
wrong about latency: a partial cannot exist before its chunk is full, so two of
the 4,115 ms it took to show a first word were unreachable by any setting.
"""

from __future__ import annotations

import pytest

from marvi_agent.parakeet_stt import (
    DEFAULT_CHUNK,
    DEFAULT_LOOKAHEAD,
    chunk_seconds,
    lookahead_seconds,
)


@pytest.fixture(autouse=True)
def _unset(monkeypatch):
    monkeypatch.delenv("MARVI_STT_CHUNK", raising=False)
    monkeypatch.delenv("MARVI_STT_LOOKAHEAD", raising=False)


def test_the_defaults_are_what_shipped() -> None:
    assert (chunk_seconds(), lookahead_seconds()) == (DEFAULT_CHUNK, DEFAULT_LOOKAHEAD)


@pytest.mark.parametrize(
    ("setting", "expected"),
    [("1.0", 1.0), ("0.5", 0.5), ("4.0", 4.0)],
)
def test_the_chunk_follows_the_setting(setting: str, expected: float, monkeypatch) -> None:
    monkeypatch.setenv("MARVI_STT_CHUNK", setting)
    assert chunk_seconds() == expected


@pytest.mark.parametrize(
    ("setting", "expected"),
    [
        # Below half a second the recogniser re-reads more context than the
        # smaller chunk saves: 0.5s measured *slower* to a first partial than
        # 1.0s and three points worse. Clamped rather than offered.
        ("0.1", 0.5),
        ("0", 0.5),
        # And past four seconds the first word is slower than anybody waits.
        ("10", 4.0),
    ],
)
def test_an_unusable_chunk_is_clamped(setting: str, expected: float, monkeypatch) -> None:
    monkeypatch.setenv("MARVI_STT_CHUNK", setting)
    assert chunk_seconds() == expected


def test_a_bad_chunk_setting_falls_back_rather_than_crashing(monkeypatch) -> None:
    monkeypatch.setenv("MARVI_STT_CHUNK", "as fast as possible")
    assert chunk_seconds() == DEFAULT_CHUNK


def test_the_ui_presets_are_settings_the_agent_accepts() -> None:
    """The three offered pairs, and what each measured.

    Guarding the pairing rather than the numbers: a preset the agent clamps is
    a picker entry that silently does something else.
    """
    from pathlib import Path

    page = (
        Path(__file__).resolve().parents[3]
        / "apps/desktop/src/renderer/src/App.tsx"
    ).read_text(encoding="utf-8")
    assert "MARVI_STT_CHUNK: chosen.chunk" in page, "the picker no longer sets the chunk"

    import os

    for chunk, look in (("1.0", "0.8"), ("2.0", "0.8"), ("2.0", "2.0")):
        os.environ["MARVI_STT_CHUNK"], os.environ["MARVI_STT_LOOKAHEAD"] = chunk, look
        try:
            assert chunk_seconds() == float(chunk)
            assert lookahead_seconds() == float(look)
        finally:
            del os.environ["MARVI_STT_CHUNK"], os.environ["MARVI_STT_LOOKAHEAD"]
