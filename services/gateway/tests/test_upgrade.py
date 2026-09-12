"""What an install from before the speech engine changed still carries.

Marvi spoke with VibeVoice and now speaks with Kokoro. An installation that has
been running since before that is left holding a setting that names a voice
which no longer exists, and two gigabytes of model nothing loads.
"""

from __future__ import annotations

import pytest

from marvi_gateway import upgrade


@pytest.mark.parametrize(
    "configured",
    ["en-Carter_man", "en-Emma_woman", "zh-Xinran_woman"],
)
def test_a_voice_from_the_old_engine_is_replaced(configured: str) -> None:
    """These were VibeVoice speaker prompts. Kokoro has never heard of them."""
    assert upgrade.stale_voice(configured, ["am_michael", "af_heart"]) == "am_michael"


def test_a_current_voice_is_left_alone() -> None:
    assert upgrade.stale_voice("af_heart", ["am_michael", "af_heart"]) is None


def test_an_empty_setting_is_not_stale() -> None:
    """Empty means "use the default", which is a working answer."""
    assert upgrade.stale_voice("", ["am_michael"]) is None


def test_an_unknown_name_in_the_current_style_is_left_alone() -> None:
    """It might be a voice added in a version this code has not seen.

    Rewriting that takes a choice away rather than repairing one. Only the old
    engine's `language-Name_gender` shape is unmistakable enough to act on.
    """
    assert upgrade.stale_voice("am_future", ["am_michael"]) is None


def test_nothing_is_deleted_by_looking(tmp_path, monkeypatch) -> None:
    """Reporting is not removing; the storage pass does that."""
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    retired = tmp_path / "models/tts/vibevoice-realtime-0.5b"
    retired.mkdir(parents=True)
    (retired / "model.safetensors").write_bytes(b"x" * 4096)

    found = upgrade.reclaimable()

    assert len(found) == 1
    assert found[0].bytes >= 4096
    assert retired.exists(), "looking must not delete"


def test_an_install_with_nothing_left_over_reports_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))

    assert upgrade.reclaimable() == []


def test_no_leftover_is_something_an_engine_installs_to(tmp_path, monkeypatch) -> None:
    """The automatic pass deletes leftovers; one that is a live engine's
    directory would delete a working voice every day."""
    from pathlib import Path

    from marvi_gateway import storage
    from marvi_gateway.setup import catalog

    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    repo = Path(__file__).resolve().parents[3]
    live = {
        (tmp_path / component.install_to).resolve()
        for component in catalog.load(repo)
        if component.install_to
    }
    for path, _why in storage._leftover_candidates():
        assert path.resolve() not in live, path
        assert not any(path.resolve() in one.parents for one in live), path
