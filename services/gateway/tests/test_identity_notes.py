"""Standing facts about the user, where every prompt will read them.

Told out loud "I am the developer", Marvi called `remember` -- the memory store,
which is searched, so the fact only surfaces when a turn happens to look like
it. USER.md is different: it is in every prompt on every surface, every time.
The fact went to the wrong one, so she could be told who she was talking to and
not know it next time.
"""

from __future__ import annotations

import pytest

from marvi_gateway.identity import IdentityFiles, register_identity_tools
from marvi_gateway.tools import ToolRegistry


@pytest.fixture
def identity(tmp_path) -> IdentityFiles:
    return IdentityFiles(directory=tmp_path / "identity")


def test_a_fact_is_written_where_the_prompt_reads_it(identity) -> None:
    identity.note_about_user("is the developer of Marvi")

    assert "is the developer of Marvi" in identity.compose()


def test_what_was_already_there_is_kept(identity) -> None:
    """A file the user edits by hand. A tool that rewrote it would eventually
    replace something they wrote."""
    identity.write_user("- lives in Istanbul")

    identity.note_about_user("prefers short answers")

    body = identity.user_path.read_text()
    assert "lives in Istanbul" in body
    assert "prefers short answers" in body


def test_the_same_fact_twice_appears_once(identity) -> None:
    identity.note_about_user("is the developer")

    assert identity.note_about_user("is the developer") == "already known"
    assert identity.user_path.read_text().count("is the developer") == 1


def test_nothing_is_not_written(identity) -> None:
    assert identity.note_about_user("   ") == "nothing to add"


def test_the_tool_is_not_confirmed(identity) -> None:
    """Asking permission to remember something the user just said about
    themselves is the kind of politeness that makes an assistant tiring."""
    registry = ToolRegistry()
    register_identity_tools(registry, identity)

    assert registry.get("note_about_user").sensitive is False


def test_the_tool_writes_through_the_registry(identity) -> None:
    registry = ToolRegistry()
    register_identity_tools(registry, identity)
    spec = registry.get("note_about_user")

    registry.execute(spec, registry.validate(spec, {"fact": "is the developer"}))

    assert "is the developer" in identity.user_path.read_text()
