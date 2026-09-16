"""Cortex exported as an Obsidian vault."""

from __future__ import annotations

import pytest

from marvi_gateway import cli, vault
from marvi_gateway.memory import MemoryStore


def _memory(tmp_path):
    path = tmp_path / "memory.db"
    store = MemoryStore(path)
    store.remember("Shereef", "Prefers tea over coffee.")
    store.remember("Shereef", "Works on a desktop assistant.")
    store.remember("a/b: c?", "A subject with characters Windows forbids.")
    db = store._db
    db.execute("INSERT OR IGNORE INTO entities (name, kind, at) VALUES ('Shereef', 'person', 'now')")
    db.execute("INSERT OR IGNORE INTO entities (name, kind, at) VALUES ('Marvi OS', 'project', 'now')")
    db.execute(
        "INSERT INTO relations (subject_id, predicate, object_id, at) VALUES ("
        "(SELECT id FROM entities WHERE name = 'Shereef'), 'builds', "
        "(SELECT id FROM entities WHERE name = 'Marvi OS'), 'now')"
    )
    db.commit()
    return path


def test_one_note_per_subject_with_links_and_an_index(tmp_path) -> None:
    out = tmp_path / "vault"
    counts = vault.export(_memory(tmp_path), out)

    assert counts == {"notes": 4, "memories": 3, "links": 1}
    shereef = (out / "Shereef.md").read_text(encoding="utf-8")
    assert "Prefers tea over coffee." in shereef and "- builds [[Marvi OS]]" in shereef
    assert (out / "Marvi OS.md").is_file()  # a link target gets a note even with no memories
    assert (out / "a-b- c.md").is_file()
    assert "[[Shereef]]" in (out / "Marvi Cortex.md").read_text(encoding="utf-8")


def test_case_collisions_get_distinct_files() -> None:
    names = vault._note_names(["Tea", "tea", "Marvi Cortex"])
    assert len({n.lower() for n in names.values()}) == 3


def test_the_cli_writes_the_vault(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("MARVI_MEMORY_DB", str(_memory(tmp_path)))
    assert cli.main(["memory", "export", "--obsidian", str(tmp_path / "v")]) == 0
    assert "wrote 4 notes" in capsys.readouterr().out
    assert cli.main(["memory", "export"]) == 0
    assert "Prefers tea" in capsys.readouterr().out


def test_a_scheduled_export_writes_the_vault(tmp_path, monkeypatch) -> None:
    """S8: the nightly vault is the cron action, not a second implementation."""
    from marvi_gateway import schedule as schedule_module

    monkeypatch.setenv("MARVI_MEMORY_DB", str(_memory(tmp_path)))
    store = schedule_module.ScheduleStore(tmp_path / "schedules.db")
    scheduler = schedule_module.Scheduler(store)
    target = tmp_path / "vault"

    job = store.add("Nightly notes", "export_memory", "cron", "0 3 * * *", str(target))
    ran = scheduler.fire(job.id)

    assert "Exported 3 memories" in ran["output"]
    assert (target / "Marvi Cortex.md").is_file()


def test_an_export_with_nowhere_to_go_says_so(tmp_path, monkeypatch) -> None:
    from marvi_gateway import schedule as schedule_module

    monkeypatch.setenv("MARVI_MEMORY_DB", str(_memory(tmp_path)))
    store = schedule_module.ScheduleStore(tmp_path / "schedules.db")
    scheduler = schedule_module.Scheduler(store)
    job = store.add("No folder", "export_memory", "cron", "0 3 * * *")

    # A failing job is recorded, not raised: one bad job must not stop the rest.
    ran = scheduler.fire(job.id)
    assert ran["ok"] is False and "folder" in ran["detail"]
