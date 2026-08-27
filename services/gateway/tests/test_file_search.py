"""Search over listing.

`file_list` answers "what is in this folder", which is almost never the
question. The question is "where is this", and answering it by listing means
the model gets a folder's worth of names, most of them irrelevant, and has to
guess which to open. It guessed wrong in a real session and told the user their
file did not exist.

Anthropic's own guidance for tool authors puts it plainly: build `search_x`,
not `list_x`, because a tool that returns everything spends the context window
on things nobody asked about.
"""

from __future__ import annotations

import pytest

from marvi_gateway.filepolicy import ROOT_SETTING
from marvi_gateway.workspace import Workspace, WorkspaceRefusedError


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv(ROOT_SETTING, str(tmp_path))
    monkeypatch.delenv("MARVI_FILE_READ_SCOPE", raising=False)
    monkeypatch.delenv("MARVI_PATH_BLACKLIST", raising=False)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "voice.py").write_text(
        "LEAD_SECONDS = 0.6\n\n\ndef speak():\n    return LEAD_SECONDS\n", encoding="utf-8"
    )
    (tmp_path / "src" / "notes.md").write_text("nothing to see\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Marvi\nLEAD_SECONDS is tunable.\n", encoding="utf-8")
    return Workspace()


def test_it_finds_the_line_not_just_the_file(workspace) -> None:
    """A line number is what makes the next call a read of one place rather
    than of one whole file."""
    found = workspace.search(query="LEAD_SECONDS", name="*.py")

    assert [(m["path"], m["line"]) for m in found["matches"]] == [
        ("src/voice.py", 1),
        ("src/voice.py", 5),
    ]
    assert found["matches"][0]["text"] == "LEAD_SECONDS = 0.6"


def test_it_finds_files_by_name_alone(workspace) -> None:
    found = workspace.search(name="*.md")

    assert sorted(m["path"] for m in found["matches"]) == ["README.md", "src/notes.md"]


def test_both_filters_narrow_together(workspace) -> None:
    """The useful question is usually both at once, and chaining two tools to
    ask it is two round trips and a list in between that nobody wanted."""
    found = workspace.search(query="LEAD_SECONDS", name="*.md")

    assert [m["path"] for m in found["matches"]] == ["README.md"]


def test_asking_for_nothing_is_refused_with_what_to_pass(workspace) -> None:
    with pytest.raises(WorkspaceRefusedError, match="query"):
        workspace.search()


def test_a_broken_regular_expression_says_what_to_do(workspace) -> None:
    """"bad escape" with no hint sends a model into rewriting the same broken
    pattern."""
    with pytest.raises(WorkspaceRefusedError, match="not a valid regular expression"):
        workspace.search(query="(unclosed")


def test_a_truncated_result_says_it_was_truncated(workspace, tmp_path) -> None:
    """A cut result read as a complete one is how "not found" becomes "not
    there"."""
    (tmp_path / "many.txt").write_text("hit\n" * 50, encoding="utf-8")

    found = workspace.search(query="hit", limit=5)

    assert len(found["matches"]) == 5
    assert "more" in found


def test_it_does_not_walk_into_the_git_directory(workspace, tmp_path) -> None:
    """`.git` and `node_modules` are most of the files in a repository and none
    of them is what anybody meant."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("LEAD_SECONDS\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("LEAD_SECONDS\n", encoding="utf-8")

    found = workspace.search(query="LEAD_SECONDS")

    assert all(".git" not in m["path"] and "node_modules" not in m["path"] for m in found["matches"])


def test_binary_files_are_not_searched(workspace, tmp_path) -> None:
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\x00\x00LEAD_SECONDS")

    found = workspace.search(query="LEAD_SECONDS")

    assert all(not m["path"].endswith(".png") for m in found["matches"])


def test_a_blacklisted_folder_inside_the_search_path_is_skipped(
    workspace, tmp_path, monkeypatch
) -> None:
    """Judged file by file rather than only at the root, which cannot see it."""
    (tmp_path / "private").mkdir()
    (tmp_path / "private" / "diary.md").write_text("LEAD_SECONDS\n", encoding="utf-8")
    monkeypatch.setenv("MARVI_PATH_BLACKLIST", str(tmp_path / "private"))

    found = workspace.search(query="LEAD_SECONDS")

    assert all("private" not in m["path"] for m in found["matches"])


def test_searching_outside_the_workspace_obeys_the_read_scope(
    workspace, tmp_path_factory, monkeypatch
) -> None:
    outside = tmp_path_factory.mktemp("elsewhere")
    (outside / "other.md").write_text("LEAD_SECONDS\n", encoding="utf-8")

    with pytest.raises(WorkspaceRefusedError, match="strict"):
        workspace.search(query="LEAD_SECONDS", path=str(outside))

    monkeypatch.setenv("MARVI_FILE_READ_SCOPE", "general")
    assert workspace.search(query="LEAD_SECONDS", path=str(outside))["matches"]


def test_a_sweep_that_stopped_early_is_not_reported_as_a_result(
    workspace, tmp_path, monkeypatch
) -> None:
    """The bug this tool exists to fix, reproduced one layer up.

    Searching the real repository returned no matches and "there are more",
    because thousands of vendored files came alphabetically before the source.
    An empty list plus "there are more" reads as "looked everywhere, found
    nothing" -- which is exactly the wrong conclusion.
    """
    monkeypatch.setattr("marvi_gateway.workspace.SEARCH_SECONDS", -1.0)

    found = workspace.search(query="LEAD_SECONDS")

    assert found["matches"] == []
    assert "incomplete" in found
    assert "not a result" in found["incomplete"]
    # And never the other message, which would mean the opposite.
    assert "more" not in found


def test_finding_the_limit_and_stopping_early_are_different_answers(workspace, tmp_path) -> None:
    (tmp_path / "many.txt").write_text("hit\n" * 50, encoding="utf-8")

    found = workspace.search(query="hit", limit=5)

    assert len(found["matches"]) == 5
    assert "more" in found
    assert "incomplete" not in found


def test_build_output_is_not_searched(workspace, tmp_path) -> None:
    """`target/` is fourteen gigabytes across this repository's crates against
    about four megabytes of source."""
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "huge.rs").write_text("LEAD_SECONDS\n", encoding="utf-8")

    found = workspace.search(query="LEAD_SECONDS")

    assert all("target" not in m["path"] for m in found["matches"])
