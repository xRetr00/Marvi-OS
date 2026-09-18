"""The whole workspace, snapshotted before a command that could lose it.

Real git against a real workspace: a shadow repository is the feature, and a
mock of it would test nothing worth knowing.
"""

from __future__ import annotations

import shutil

import pytest

from marvi_gateway import treecheck
from marvi_gateway.filepolicy import ROOT_SETTING
from marvi_gateway.workspace import Workspace, WorkspaceRefusedError

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (root / "notes.md").write_text("the notes\n", encoding="utf-8")
    monkeypatch.setenv(ROOT_SETTING, str(root))
    monkeypatch.setenv("MARVI_HOME", str(tmp_path / "home"))
    for name in ("MARVI_FILE_READ_SCOPE", "MARVI_FILE_WRITE_SCOPE", "MARVI_PATH_BLACKLIST"):
        monkeypatch.delenv(name, raising=False)
    return Workspace()


def test_what_counts_as_able_to_lose_work() -> None:
    for command in (
        "Remove-Item -Recurse -Force src",
        "rm -rf build",
        "git reset --hard HEAD~1",
        "git clean -fd",
        "mv notes.md old.md",
        "echo hi > notes.md",
        "sed -i s/a/b/ notes.md",
    ):
        assert treecheck.looks_destructive(command), command

    for command in ("git status", "npm test", "ls -la", "python -m pytest -q", "cat notes.md"):
        assert not treecheck.looks_destructive(command), command


def test_a_destructive_command_is_snapshotted_and_can_be_undone(workspace) -> None:
    root = workspace.root
    ran = workspace.run("Remove-Item -Recurse -Force src", timeout=60)

    assert ran["exit_code"] == 0
    assert not (root / "src").exists()  # it really deleted it
    assert ran["snapshot"], "the command was not snapshotted"

    put_back = workspace.restore(checkpoint=ran["snapshot"])

    assert (root / "src" / "main.py").read_text(encoding="utf-8") == "print('hello')\n"
    assert put_back["what"] == "the whole workspace"
    # Undoing the undo is the same operation again.
    assert put_back["previous_saved_as"]


def test_one_file_can_be_taken_from_a_workspace_snapshot(workspace) -> None:
    root = workspace.root
    first = treecheck.snapshot(root, "before the test")
    (root / "notes.md").write_text("ruined\n", encoding="utf-8")
    (root / "src" / "main.py").write_text("also ruined\n", encoding="utf-8")

    workspace.restore("notes.md", first["id"])

    assert (root / "notes.md").read_text(encoding="utf-8") == "the notes\n"
    # Only what was asked for: the other file is left as it is now.
    assert (root / "src" / "main.py").read_text(encoding="utf-8") == "also ruined\n"


def test_an_ordinary_command_takes_no_snapshot(workspace) -> None:
    ran = workspace.run("Write-Output ok", timeout=60)
    assert "snapshot" not in ran


def test_the_users_own_repository_is_never_touched(workspace) -> None:
    """The whole point of a shadow store: their `git status` shows nothing."""
    root = workspace.root
    import subprocess

    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "theirs"],
        cwd=root,
        check=True,
    )
    before = subprocess.run(
        ["git", "log", "--format=%s"], cwd=root, capture_output=True, text=True, check=True
    ).stdout

    workspace.run("Remove-Item -Force notes.md", timeout=60)

    after = subprocess.run(
        ["git", "log", "--format=%s"], cwd=root, capture_output=True, text=True, check=True
    ).stdout
    assert before == after  # no commit of Marvi's in their history
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=True
    ).stdout
    # Their deleted file shows, and nothing of Marvi's does.
    assert "notes.md" in status
    assert ".marvi" not in status and "checkpoints" not in status


def test_both_kinds_of_checkpoint_are_listed_together(workspace) -> None:
    workspace.write("notes.md", "changed by a tool\n")  # a file copy
    workspace.run("Remove-Item -Force notes.md", timeout=60)  # a tree snapshot

    rows = workspace.list_checkpoints(limit=10)

    kinds = {row["kind"] for row in rows}
    assert {"file", "tree"} <= kinds
    tree = next(row for row in rows if row["kind"] == "tree")
    assert "Remove-Item" in tree["why"]


def test_restoring_needs_something_to_restore(workspace) -> None:
    with pytest.raises(WorkspaceRefusedError, match="which file"):
        workspace.restore()
