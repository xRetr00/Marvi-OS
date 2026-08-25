from __future__ import annotations

import json
from pathlib import Path

from marvi_gateway.setup import pocket
from marvi_gateway.setup.catalog import for_capability
from marvi_gateway.setup.installer import Outcome, install, plan


def test_setup_prepares_pocket_tts_and_records_the_package(monkeypatch, tmp_path) -> None:
    cache = tmp_path / "pocket-tts" / "huggingface"
    monkeypatch.setattr(pocket, "pocket_cache_dir", lambda: cache)
    monkeypatch.setattr(pocket, "version", lambda _name: "2.1.0")

    class Prepared:
        def prepare(self):
            cache.mkdir(parents=True)
            return {"ready": True, "voice": "alba", "latency_ms": 12.0}

    monkeypatch.setattr(pocket, "Announcer", Prepared)

    assert pocket.installed() is False
    assert pocket.install()["ready"] is True
    assert pocket.installed() is True
    assert json.loads(pocket.marker_path().read_text(encoding="utf-8"))["package"] == "2.1.0"


def test_setup_catalog_exposes_pocket_tts_for_announcements() -> None:
    repo = Path(__file__).resolve().parents[3]
    components = {component.name: component for component in for_capability(repo, "announce")}

    pocket_tts = components["pocket-tts"]
    assert pocket_tts.kind == "command"
    assert pocket_tts.project == "services/gateway"
    assert pocket_tts.install_to == "models/pocket-tts"


def test_a_prepared_pocket_component_is_not_run_again(monkeypatch) -> None:
    repo = Path(__file__).resolve().parents[3]
    component = next(
        component for component in for_capability(repo, "announce") if component.name == "pocket-tts"
    )
    monkeypatch.setattr(
        "marvi_gateway.setup.installer.command_installed", lambda _component, _repo: True
    )
    monkeypatch.setattr(
        "marvi_gateway.setup.installer._run_command",
        lambda *_args: Outcome("pocket-tts", False, "must not run"),
    )

    outcome = install(component, repo)

    assert outcome.ok is True and outcome.skipped is True
    assert plan([component], repo)["already_installed"] == ["pocket-tts"]
