"""Changing part of a file without rewriting it.

`file_write` was the only way to alter a line, which means reproducing the
whole file from memory to change one word. That is unreliable from any model
and impossible from a voice turn, and it is why a file Marvi "edited" came back
missing everything she had not remembered.

The tests that matter here are the Windows ones. A model sends its `old` and
`new` with bare newlines because that is what JSON carries; the file on this
machine has CRLF; and a plain `str.replace` finds nothing and reports the text
as absent, which is both wrong and unactionable.
"""

from __future__ import annotations

import pytest

from marvi_gateway.filepolicy import ROOT_SETTING
from marvi_gateway.workspace import Workspace, WorkspaceRefusedError


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv(ROOT_SETTING, str(tmp_path))
    monkeypatch.delenv("MARVI_FILE_READ_SCOPE", raising=False)
    monkeypatch.delenv("MARVI_FILE_WRITE_SCOPE", raising=False)
    monkeypatch.delenv("MARVI_PATH_BLACKLIST", raising=False)
    return Workspace()


def test_it_changes_one_passage_and_leaves_the_rest(workspace, tmp_path) -> None:
    target = tmp_path / "note.md"
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")

    result = workspace.edit("note.md", "two", "TWO")

    assert result["changed"] is True
    assert target.read_text(encoding="utf-8") == "one\nTWO\nthree\n"


def test_a_crlf_file_matches_newlines_the_model_sent(workspace, tmp_path) -> None:
    """The Windows case, and the reason this is not `str.replace`."""
    target = tmp_path / "note.md"
    target.write_bytes(b"first\r\nsecond\r\nthird\r\n")

    # As a model sends it: bare newlines, because that is what JSON carries.
    result = workspace.edit("note.md", "first\nsecond", "first\nSECOND")

    assert result["changed"] is True
    assert target.read_bytes() == b"first\r\nSECOND\r\nthird\r\n"


def test_the_file_keeps_its_line_endings(workspace, tmp_path) -> None:
    """A one-word change must not arrive as a diff against every line."""
    target = tmp_path / "note.md"
    target.write_bytes(b"alpha\r\nbeta\r\n")

    workspace.edit("note.md", "beta", "gamma")

    assert b"\r\n" in target.read_bytes()
    assert b"\n\n" not in target.read_bytes()


def test_a_byte_order_mark_survives(workspace, tmp_path) -> None:
    """Windows editors write them, and a file that loses one reads as changed
    on its first line."""
    target = tmp_path / "note.md"
    target.write_bytes(b"\xef\xbb\xbfalpha\r\n")

    workspace.edit("note.md", "alpha", "beta")

    assert target.read_bytes().startswith(b"\xef\xbb\xbf")


def test_ambiguity_is_refused_with_the_count(workspace, tmp_path) -> None:
    """Taking the first is how an edit lands in the wrong function."""
    target = tmp_path / "code.py"
    target.write_text("return None\nreturn None\n", encoding="utf-8")

    with pytest.raises(WorkspaceRefusedError, match="appears 2 times"):
        workspace.edit("code.py", "return None", "return 1")


def test_replace_all_takes_them_all(workspace, tmp_path) -> None:
    target = tmp_path / "code.py"
    target.write_text("x = 1\nx = 1\n", encoding="utf-8")

    result = workspace.edit("code.py", "x = 1", "x = 2", replace_all=True)

    assert result["replacements"] == 2
    assert target.read_text(encoding="utf-8") == "x = 2\nx = 2\n"


def test_re_sending_an_applied_edit_is_a_no_op_not_an_error(workspace, tmp_path) -> None:
    """The commonest patch failure in practice. An error here is what sends a
    model into a loop of re-reading and re-patching."""
    target = tmp_path / "note.md"
    target.write_text("done\n", encoding="utf-8")

    result = workspace.edit("note.md", "todo", "done")

    assert result["changed"] is False
    assert "already applied" in result["note"]


def test_text_that_is_really_absent_says_what_to_do(workspace, tmp_path) -> None:
    target = tmp_path / "note.md"
    target.write_text("nothing like it\n", encoding="utf-8")

    with pytest.raises(WorkspaceRefusedError, match="could not find"):
        workspace.edit("note.md", "missing passage", "new")


def test_a_file_that_does_not_exist_is_not_created(workspace) -> None:
    with pytest.raises(WorkspaceRefusedError, match="not a file"):
        workspace.edit("nowhere.md", "a", "b")


def test_editing_obeys_the_write_scope(workspace, tmp_path_factory, monkeypatch) -> None:
    outside = tmp_path_factory.mktemp("elsewhere") / "other.md"
    outside.write_text("alpha\n", encoding="utf-8")

    with pytest.raises(WorkspaceRefusedError, match="strict"):
        workspace.edit(str(outside), "alpha", "beta")

    monkeypatch.setenv("MARVI_FILE_WRITE_SCOPE", "general")
    assert workspace.edit(str(outside), "alpha", "beta")["changed"] is True


def test_writing_a_whole_file_does_not_rewrite_its_newlines(workspace, tmp_path) -> None:
    """Python's text mode translates every newline to CRLF on Windows, which
    silently rewrites the endings of any file Marvi touches."""
    workspace.write("fresh.txt", "one\ntwo\n")

    assert (tmp_path / "fresh.txt").read_bytes() == b"one\ntwo\n"
