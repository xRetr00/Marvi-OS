"""The daily storage pass, and the growth it exists to stop.

Every test here is about deleting the right thing and nothing else: a pass that
missed a leftover costs disk, and one that took a live file costs a working
Marvi.
"""

from __future__ import annotations

import os
import time

import pytest

from marvi_gateway import runtime, storage
from marvi_gateway.setup import catalog


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    monkeypatch.delenv("MARVI_LOG_DIR", raising=False)
    monkeypatch.setattr(storage.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    return tmp_path


def _aged(path, seconds_ago: float) -> None:
    then = time.time() - seconds_ago
    os.utime(path, (then, then))


def test_only_the_newest_backup_of_each_thing_is_kept(home) -> None:
    for name, age in (
        ("memory.sqlite3.before-dedup-20260907", 300),
        ("memory.sqlite3.bak", 200),
        ("memory.sqlite3.before-junk-cleanup", 100),
    ):
        (home / name).write_text("x")
        _aged(home / name, age)
    (home / "memory.sqlite3").write_text("live")
    vision = home / "plugin-data" / "smart_room" / "vision"
    vision.mkdir(parents=True)
    (vision / "faces.sqlite3.20260911.bak").write_text("x")
    _aged(vision / "faces.sqlite3.20260911.bak", 100)
    (vision / "faces.sqlite3.20260912.bak").write_text("x")
    (vision.parent / "vision-backup-20260904-113413").mkdir()

    storage.housekeep()

    assert (home / "memory.sqlite3").exists(), "the live file is not a backup"
    assert (home / "memory.sqlite3.before-junk-cleanup").exists()
    assert not (home / "memory.sqlite3.bak").exists()
    assert not (home / "memory.sqlite3.before-dedup-20260907").exists()
    assert [p.name for p in vision.glob("*.bak")] == ["faces.sqlite3.20260912.bak"]
    assert (vision.parent / "vision-backup-20260904-113413").exists(), "the only one of its kind"


def test_logs_are_cycled_every_three_days_and_the_last_cycle_is_kept(home) -> None:
    logs = home / "logs"
    logs.mkdir()
    (logs / "agent.log").write_text("today\n")
    (logs / "agent.log.1").write_text("last week\n")
    (logs / "agent.log.2").write_text("older\n")

    now = time.time()
    storage.housekeep(now)
    assert (logs / "agent.log").read_text() == ""
    assert (logs / "agent.log.1").read_text() == "today\n"
    assert not (logs / "agent.log.2").exists()

    (logs / "agent.log").write_text("tomorrow\n")
    storage.housekeep(now + storage.DAY)
    assert (logs / "agent.log").read_text() == "tomorrow\n", "not before three days"

    storage.housekeep(now + storage.LOG_CYCLE_SECONDS)
    assert (logs / "agent.log.1").read_text() == "tomorrow\n"


def test_leftovers_and_old_temporary_files_go_and_new_ones_stay(home) -> None:
    retired = home / "models" / "vision" / "models"
    retired.mkdir(parents=True)
    (retired / "det_10g.onnx").write_bytes(b"x" * 100)
    stale = home / "tmp" / "marvi-location-proof-abc"
    stale.mkdir()
    _aged(stale, 2 * storage.DAY)
    fresh = home / "tmp" / "marvi-agent-tests-xyz"
    fresh.mkdir()

    report = storage.housekeep()

    assert not (home / "models" / "vision").exists()
    assert not stale.exists()
    assert fresh.exists(), "a test run from an hour ago may still be running"
    assert report["freed_bytes"] >= 100


def test_voice_needs_only_the_selected_engines(monkeypatch) -> None:
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    monkeypatch.setenv("MARVI_STT_ENGINE", "nemotron-3.5")
    monkeypatch.setenv("MARVI_TTS_ENGINE", "voxtream2")
    voice = {c.name for c in catalog.for_capability(repo, "voice")}

    assert {"stt-nemotron-model", "stt-nemotron-runtime", "tts-voxtream-model"} <= voice
    assert "voice-stt" not in voice, "Parakeet is optional once Nemotron is chosen"
    assert "voice-tts" not in voice
    assert "livekit" not in catalog.unselected_engine_components()


def test_room_polls_do_not_fill_the_audit(tmp_path) -> None:
    store = runtime.RuntimeStore(audit_path=tmp_path / "audit.jsonl")
    for _ in range(5):
        store.audit("requested", "room_state", {})
        store.audit("executed", "room_health", {})
    store.audit("failed", "room_state", {}, detail="sidecar down")
    store.audit("executed", "set_light", {"on": True})

    assert [e.tool for e in store.recent_audit()] == ["set_light", "room_state"]


def test_the_audit_is_trimmed_past_its_cap(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runtime, "AUDIT_MAX_BYTES", 2_000)
    monkeypatch.setattr(runtime, "AUDIT_KEEP_LINES", 5)
    store = runtime.RuntimeStore(audit_path=tmp_path / "audit.jsonl")
    for n in range(40):
        store.audit("executed", "set_light", {"n": n})

    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(lines) <= 20
    assert '"n":39' in lines[-1], "the newest are the ones kept"
