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
    """Two gigabytes of somebody's disk is a decision, not a migration.

    The files are re-downloadable, but when to spend that bandwidth is theirs
    to choose -- so this reports and `marvi models prune` removes.
    """
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    retired = tmp_path / upgrade.RETIRED_MODELS[0]
    retired.mkdir(parents=True)
    (retired / "model.safetensors").write_bytes(b"x" * 4096)

    found = upgrade.reclaimable()

    assert len(found) == 1
    assert found[0].bytes >= 4096
    assert retired.exists(), "looking must not delete"


def test_an_install_with_nothing_left_over_reports_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))

    assert upgrade.reclaimable() == []


def test_the_retired_path_is_the_one_that_was_actually_used() -> None:
    """A typo here means the leftover is never found and never reclaimed."""
    from pathlib import Path

    catalog = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "marvi_gateway"
        / "setup"
        / "catalog.py"
    ).read_text(encoding="utf-8")

    # The path Kokoro uses now must not be the one being reclaimed.
    assert 'install_to="models/tts/kokoro-82m"' in catalog
    assert "models/tts/kokoro-82m" not in upgrade.RETIRED_MODELS
