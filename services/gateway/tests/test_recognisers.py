"""The recogniser catalog behind Settings > Speech recognition."""

from __future__ import annotations

import pytest

from marvi_gateway import recognisers


@pytest.fixture(autouse=True)
def _elsewhere(tmp_path, monkeypatch):
    monkeypatch.setenv("MARVI_INSTALL_ROOT", str(tmp_path))
    monkeypatch.delenv(recognisers.ENGINE_ENV, raising=False)
    recognisers.catalog.cache_clear()
    yield
    recognisers.catalog.cache_clear()


def _install(root) -> None:
    """Everything the Nemotron adapter looks for, and nothing more."""
    for path in (
        root / "models/stt/nemotron-3.5-asr-streaming-0.6b/nemotron-3.5-asr-streaming-0.6b-f16.gguf",
        root / "runtimes/parakeet-cpp/lib/parakeet.dll",
        root / "runtimes/parakeet-cpp/cudart/cudart64_12.dll",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


def test_the_default_is_the_accurate_one() -> None:
    assert recognisers.selected() == "parakeet-tdt"


def test_the_in_process_recogniser_needs_no_install(tmp_path) -> None:
    parakeet = next(item for item in recognisers.engines() if item.id == "parakeet-tdt")
    assert parakeet.available() is True


def test_nemotron_is_unavailable_until_all_three_pieces_are_there(tmp_path) -> None:
    nemotron = next(item for item in recognisers.engines() if item.id == "nemotron-3.5")
    assert nemotron.available() is False
    # The weights alone are the trap: the picker would offer it and the agent
    # would fall back to the default the moment it was chosen.
    weights = (
        tmp_path
        / "models/stt/nemotron-3.5-asr-streaming-0.6b/nemotron-3.5-asr-streaming-0.6b-f16.gguf"
    )
    weights.parent.mkdir(parents=True, exist_ok=True)
    weights.write_bytes(b"")
    assert nemotron.available() is False
    # And cuBLAS is the piece that fails latest: the library loads, then dies
    # on the first frame of audio.
    library = tmp_path / "runtimes/parakeet-cpp/lib/parakeet.dll"
    library.parent.mkdir(parents=True, exist_ok=True)
    library.write_bytes(b"")
    assert nemotron.available() is False
    _install(tmp_path)
    assert nemotron.available() is True


def test_an_unknown_choice_falls_back_rather_than_failing(monkeypatch) -> None:
    monkeypatch.setenv(recognisers.ENGINE_ENV, "whisper-tiny")
    assert recognisers.selected() == "parakeet-tdt"


def test_a_known_choice_is_honoured(monkeypatch) -> None:
    monkeypatch.setenv(recognisers.ENGINE_ENV, "nemotron-3.5")
    assert recognisers.selected() == "nemotron-3.5"


def test_the_catalog_matches_what_the_agent_can_actually_load(monkeypatch) -> None:
    """The two lists are in different services and drift silently.

    `parakeet_stt.ENGINES` is what the agent will build; this catalog is what
    the picker offers. An entry in one and not the other is either a recogniser
    nobody can choose or a choice that quietly does nothing.
    """
    from pathlib import Path

    agent_src = Path(__file__).resolve().parents[2] / "agent" / "src"
    monkeypatch.syspath_prepend(str(agent_src))
    from marvi_agent.parakeet_stt import ENGINES

    assert {item.id for item in recognisers.engines()} == set(ENGINES)
