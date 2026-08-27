"""Where Marvi may reach, and what she may never touch.

The three questions are tested separately because they are three settings:
reading reach, writing reach, and the blacklist that holds over both. The one
that matters most is the last -- `general` is only offered because there is a
stop list, so a blacklist that stopped applying in `general` would quietly turn
a considered setting into an unconditional one.
"""

from __future__ import annotations

import os
import sys

import pytest

from marvi_gateway.filepolicy import (
    BLACKLIST_SETTING,
    GENERAL,
    READ_SETTING,
    ROOT_SETTING,
    STRICT,
    WRITE_SETTING,
    Access,
    PathRefusedError,
    describe,
)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    (tmp_path / "notes.md").write_text("hello", encoding="utf-8")
    monkeypatch.setenv(ROOT_SETTING, str(tmp_path))
    monkeypatch.delenv(READ_SETTING, raising=False)
    monkeypatch.delenv(WRITE_SETTING, raising=False)
    monkeypatch.delenv(BLACKLIST_SETTING, raising=False)
    return tmp_path


# -- reach -------------------------------------------------------------------


def test_strict_is_the_default_for_both(workspace) -> None:
    """A missing setting is the narrow one, not the wide one."""
    access = Access.from_env()
    assert access.read_scope == STRICT
    assert access.write_scope == STRICT


def test_an_unreadable_scope_reads_as_strict(workspace, monkeypatch) -> None:
    """A typo in a settings field must never be what opens the disk."""
    monkeypatch.setenv(WRITE_SETTING, "genral")
    assert Access.from_env().write_scope == STRICT


def test_strict_refuses_outside_and_allows_inside(workspace, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("elsewhere") / "other.md"
    outside.write_text("hi", encoding="utf-8")
    access = Access.from_env()

    assert access.resolve("notes.md", write=False) == (workspace / "notes.md").resolve()
    with pytest.raises(PathRefusedError, match="strict"):
        access.resolve(str(outside), write=False)


def test_reading_can_be_general_while_writing_stays_strict(
    workspace, tmp_path_factory, monkeypatch
) -> None:
    """The asymmetry one switch could not express, and the reason there are two."""
    monkeypatch.setenv(READ_SETTING, GENERAL)
    outside = tmp_path_factory.mktemp("elsewhere") / "other.md"
    outside.write_text("hi", encoding="utf-8")
    access = Access.from_env()

    assert access.resolve(str(outside), write=False) == outside.resolve()
    with pytest.raises(PathRefusedError):
        access.resolve(str(outside), write=True)


def test_a_relative_path_always_means_the_workspace(workspace, monkeypatch) -> None:
    """Even in general mode. The alternative is the Gateway's working
    directory, which nobody chose and which moves."""
    monkeypatch.setenv(READ_SETTING, GENERAL)
    assert Access.from_env().resolve("notes.md", write=False) == (
        workspace / "notes.md"
    ).resolve()


def test_dot_dot_is_caught_by_the_same_check(workspace) -> None:
    with pytest.raises(PathRefusedError):
        Access.from_env().resolve("../escape.md", write=False)


# -- the blacklist -----------------------------------------------------------


def test_the_blacklist_holds_in_general_mode(workspace, tmp_path_factory, monkeypatch) -> None:
    """The whole reason general mode can be offered at all."""
    secret = tmp_path_factory.mktemp("private")
    monkeypatch.setenv(READ_SETTING, GENERAL)
    monkeypatch.setenv(WRITE_SETTING, GENERAL)
    monkeypatch.setenv(BLACKLIST_SETTING, str(secret))

    with pytest.raises(PathRefusedError, match="blacklist"):
        Access.from_env().resolve(str(secret / "diary.txt"), write=False)


def test_the_blacklist_holds_inside_the_workspace(workspace, monkeypatch) -> None:
    """Asked in the other order, a blacklisted path inside the workspace would
    come back allowed because the scope check passed first."""
    monkeypatch.setenv(BLACKLIST_SETTING, str(workspace / "notes.md"))

    with pytest.raises(PathRefusedError, match="blacklist"):
        Access.from_env().resolve("notes.md", write=False)


def test_a_blacklisted_folder_covers_what_is_under_it(workspace, monkeypatch) -> None:
    (workspace / "private").mkdir()
    monkeypatch.setenv(BLACKLIST_SETTING, str(workspace / "private"))

    with pytest.raises(PathRefusedError, match="blacklist"):
        Access.from_env().resolve("private/deep/thing.txt", write=True)


def test_a_wildcard_entry_matches_by_name_anywhere(workspace, monkeypatch) -> None:
    monkeypatch.setenv(BLACKLIST_SETTING, "*.key")
    (workspace / "sub").mkdir()

    with pytest.raises(PathRefusedError, match="blacklist"):
        Access.from_env().resolve("sub/server.key", write=False)


def test_several_entries_use_the_platform_separator(workspace, monkeypatch) -> None:
    monkeypatch.setenv(BLACKLIST_SETTING, os.pathsep.join(["*.key", "*.crt"]))
    assert Access.from_env().blacklist == ["*.key", "*.crt"]


# -- what cannot be allowed --------------------------------------------------


def test_env_files_are_refused_even_for_reading(workspace, monkeypatch) -> None:
    """A key read into a reply is a key on its way out."""
    monkeypatch.setenv(READ_SETTING, GENERAL)
    (workspace / ".env").write_text("KEY=secret", encoding="utf-8")

    with pytest.raises(PathRefusedError, match="always refused"):
        Access.from_env().resolve(".env", write=False)


def test_marvi_own_state_is_refused(workspace, tmp_path_factory, monkeypatch) -> None:
    """Her own keys, her own memory, her own audit trail."""
    home = tmp_path_factory.mktemp("marvi-home")
    monkeypatch.setenv("MARVI_HOME", str(home))
    monkeypatch.setenv(READ_SETTING, GENERAL)
    monkeypatch.setenv(WRITE_SETTING, GENERAL)

    with pytest.raises(PathRefusedError, match="always refused"):
        Access.from_env().resolve(str(home / "providers.env"), write=True)


def test_a_builtin_rule_cannot_be_lifted_by_emptying_the_blacklist(
    workspace, monkeypatch
) -> None:
    monkeypatch.setenv(BLACKLIST_SETTING, "")
    monkeypatch.setenv(READ_SETTING, GENERAL)
    (workspace / "id_rsa").write_text("-----BEGIN", encoding="utf-8")

    with pytest.raises(PathRefusedError, match="always refused"):
        Access.from_env().resolve("id_rsa", write=False)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows paths")
def test_system_directories_are_readable_and_not_writable(workspace, monkeypatch) -> None:
    """Reading one is harmless and occasionally the answer to a question."""
    monkeypatch.setenv(READ_SETTING, GENERAL)
    monkeypatch.setenv(WRITE_SETTING, GENERAL)
    hosts = "C:/Windows/System32/drivers/etc/hosts"
    access = Access.from_env()

    assert access.resolve(hosts, write=False)
    with pytest.raises(PathRefusedError, match="always refused"):
        access.resolve(hosts, write=True)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows paths")
def test_case_does_not_get_you_past_a_rule(workspace, monkeypatch) -> None:
    """Two spellings of one directory are one directory."""
    monkeypatch.setenv(WRITE_SETTING, GENERAL)

    with pytest.raises(PathRefusedError, match="always refused"):
        Access.from_env().resolve("c:/wInDoWs/system32/hosts", write=True)


# -- what the settings page is told ------------------------------------------


def test_describe_lists_the_builtin_rules(workspace) -> None:
    """A deny list with invisible entries is one nobody can reason about, and
    the first time an invisible entry bites it reads as a bug."""
    page = describe()

    assert page["read_scope"] == STRICT
    assert page["root"] == str(workspace.resolve())
    assert any(rule["why"] for rule in page["builtin"])
