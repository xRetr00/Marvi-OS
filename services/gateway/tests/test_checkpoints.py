"""A file Marvi changed can be put back the way it was."""

from __future__ import annotations

import pytest

from marvi_gateway import checkpoints
from marvi_gateway.filepolicy import ROOT_SETTING
from marvi_gateway.workspace import Workspace, WorkspaceRefusedError


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "work"
    root.mkdir()
    monkeypatch.setenv(ROOT_SETTING, str(root))
    monkeypatch.setenv("MARVI_HOME", str(tmp_path / "home"))
    for name in ("MARVI_FILE_READ_SCOPE", "MARVI_FILE_WRITE_SCOPE", "MARVI_PATH_BLACKLIST"):
        monkeypatch.delenv(name, raising=False)
    return Workspace()


def test_edit_write_and_delete_can_each_be_undone(workspace) -> None:
    target = workspace.root / "note.md"
    target.write_text("original\n", encoding="utf-8")

    edited = workspace.edit("note.md", "original", "edited")
    assert edited["checkpoint"]
    workspace.restore("note.md")
    assert target.read_text(encoding="utf-8") == "original\n"

    workspace.write("note.md", "rewritten\n")
    workspace.restore("note.md")
    assert target.read_text(encoding="utf-8") == "original\n"

    deleted = workspace.delete("note.md")
    assert not target.exists() and deleted["checkpoint"]
    workspace.restore("note.md")
    assert target.read_text(encoding="utf-8") == "original\n"


def test_a_restore_is_itself_undoable_and_a_named_one_wins(workspace) -> None:
    target = workspace.root / "a.txt"
    target.write_text("v1", encoding="utf-8")
    first = workspace.write("a.txt", "v2")["checkpoint"]
    workspace.write("a.txt", "v3")

    result = workspace.restore("a.txt", first)
    assert target.read_text(encoding="utf-8") == "v1"
    assert result["previous_saved_as"]

    workspace.restore("a.txt", result["previous_saved_as"])
    assert target.read_text(encoding="utf-8") == "v3"
    listed = workspace.list_checkpoints("a.txt")
    assert listed[0]["path"] == "a.txt" and len(listed) == 4


def test_a_new_file_has_nothing_to_restore(workspace) -> None:
    written = workspace.write("new.txt", "hello")
    assert "checkpoint" not in written
    with pytest.raises(WorkspaceRefusedError, match="no checkpoint"):
        workspace.restore("new.txt")


def test_old_checkpoints_are_pruned(workspace, monkeypatch) -> None:
    monkeypatch.setattr(checkpoints, "KEEP", 3)
    target = workspace.root / "b.txt"
    target.write_text("0", encoding="utf-8")
    for n in range(1, 6):
        workspace.write("b.txt", str(n))
    assert len(workspace.list_checkpoints("b.txt", 50)) == 3
    assert len(list(checkpoints.folder().glob("*.bin"))) == 3
