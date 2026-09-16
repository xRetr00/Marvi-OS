"""`@notes.md` and `@https://…` in a typed message."""

from __future__ import annotations

import pytest

from marvi_gateway import mentions
from marvi_gateway.chat import ChatStore
from marvi_gateway.filepolicy import ROOT_SETTING
from marvi_gateway.workspace import Workspace


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "work"
    root.mkdir()
    (root / "notes.md").write_text("# Notes\nThe hotel is booked.\n", encoding="utf-8")
    (root / "two words.md").write_text("spaces are allowed\n", encoding="utf-8")
    monkeypatch.setenv(ROOT_SETTING, str(root))
    for name in ("MARVI_FILE_READ_SCOPE", "MARVI_FILE_WRITE_SCOPE", "MARVI_PATH_BLACKLIST"):
        monkeypatch.delenv(name, raising=False)
    return Workspace()


class FakeWeb:
    def extract(self, url: str, question: str = "") -> dict:
        return {"text": f"The page at {url} says hello."}


def test_what_counts_as_a_mention() -> None:
    assert mentions.parse("look at @notes.md please") == ["notes.md"]
    assert mentions.parse('read @"two words.md" now') == ["two words.md"]
    assert mentions.parse("compare @a.md, @b.md;") == ["a.md", "b.md"]
    assert mentions.parse("and @https://example.com/x") == ["https://example.com/x"]
    # Not an email address, and not the middle of a word.
    assert mentions.parse("mail me@example.com or s@lt") == []
    # One turn cannot drag in forty files.
    assert len(mentions.parse(" ".join(f"@f{n}.md" for n in range(20)))) == mentions.MAX_MENTIONS


def test_a_named_file_becomes_an_attachment(tmp_path, workspace) -> None:
    store = ChatStore(tmp_path / "chat.db")
    thread = store.create_thread("Trip")["id"]

    ids, notes = mentions.resolve("what does @notes.md say?", thread, store, workspace, FakeWeb())

    assert notes == [] and len(ids) == 1
    rows = store.pending_attachments(thread, ids)
    assert rows[0]["name"] == "notes.md"
    assert "hotel is booked" in rows[0]["extracted"]


def test_a_named_page_is_fetched_and_kept_as_text(tmp_path, workspace) -> None:
    store = ChatStore(tmp_path / "chat.db")
    thread = store.create_thread("Reading")["id"]

    ids, notes = mentions.resolve("@https://example.com/x", thread, store, workspace, FakeWeb())

    assert notes == []
    row = store.pending_attachments(thread, ids)[0]
    assert row["name"] == "example.com-x.txt"  # a URL becomes a readable filename
    assert "says hello" in row["extracted"]


def test_what_cannot_be_read_is_reported_not_swallowed(tmp_path, workspace) -> None:
    store = ChatStore(tmp_path / "chat.db")
    thread = store.create_thread("Trip")["id"]

    ids, notes = mentions.resolve("@missing.md and @notes.md", thread, store, workspace, FakeWeb())

    assert len(ids) == 1  # the one that exists still arrives
    assert notes and "missing.md" in notes[0]


def test_a_turn_with_a_mention_carries_the_file(tmp_path, workspace, monkeypatch) -> None:
    """End to end: the message is sent, and the file is on the stored turn."""
    from marvi_gateway.chat import Chat

    store = ChatStore(tmp_path / "chat.db")
    thread = store.create_thread("Trip")["id"]
    chat = Chat(store=store, workspace=workspace, web=FakeWeb())
    monkeypatch.setattr(chat, "available", lambda: True)  # no model is actually called

    list(chat.send_stream("summarise @notes.md", thread_id=thread))

    # The turn fails at the provider (there is none configured in tests), but
    # the mention was resolved before that and is attached to the turn.
    staged = store._db.execute(
        "SELECT name FROM attachments WHERE thread_id = ?", (thread,)
    ).fetchall()
    assert [row["name"] for row in staged] == ["notes.md"]
