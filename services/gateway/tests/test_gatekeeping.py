"""The doors into memory that nothing used to guard.

A turn is judged by `remembering` and a read is answered by `reading`. These
are the other two ways something reaches the store: a connector's ingest, and
the `memory_remember` tool a model calls mid-sentence. Both caused real damage
before they were gated -- see `gatekeeping`'s module docstring.
"""

from __future__ import annotations

from dataclasses import dataclass

from marvi_gateway import gatekeeping


@dataclass
class Item:
    subject: str
    body: str


class Model:
    """Answers with whatever it was built with, and records what it was asked."""

    def __init__(self, said: str) -> None:
        self.said = said
        self.asked: list[str] = []


def _answering(monkeypatch, reply: str) -> None:
    def fake_ask(client, role, system, user, max_tokens, **kwargs):
        client.asked.append(user)
        return client.said if reply is None else reply

    monkeypatch.setattr(gatekeeping.distil, "ask", fake_ask)


# -- what a connector brings in ----------------------------------------------


def test_only_the_chosen_items_are_kept(monkeypatch) -> None:
    _answering(monkeypatch, '{"keep":[0,2]}')
    items = [Item("a", "one"), Item("b", "two"), Item("c", "three")]

    kept = gatekeeping.worth_keeping(Model(""), items)

    assert [item.subject for item in kept] == ["a", "c"]


def test_an_empty_list_means_none_of_them(monkeypatch) -> None:
    """A poll of nothing but newsletters is the common case, and the right
    answer to it is to write nothing."""
    _answering(monkeypatch, '{"keep":[]}')

    assert gatekeeping.worth_keeping(Model(""), [Item("a", "one")]) == []


def test_a_model_that_says_nothing_keeps_everything(monkeypatch) -> None:
    """An empty *list* is a decision. An empty *string* is a model that did
    not answer, and discarding a week of mail on that would be the failure
    this file exists to prevent."""
    _answering(monkeypatch, "")
    items = [Item("a", "one"), Item("b", "two")]

    assert gatekeeping.worth_keeping(Model(""), items) == items


def test_a_broken_gate_keeps_everything(monkeypatch) -> None:
    """Fails open, deliberately. A store with newsletters in it can be
    cleaned; a week of missing correspondence cannot be recovered."""

    def boom(*_args, **_kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(gatekeeping.distil, "ask", boom)
    items = [Item("a", "one")]

    assert gatekeeping.worth_keeping(Model(""), items) == items
    assert gatekeeping.worth_keeping(None, items) == items


def test_tracking_whitespace_is_collapsed_before_the_model_reads_it(monkeypatch) -> None:
    """Marketing mail pads its body with hundreds of invisible characters.
    Left alone they are most of what the judge would see."""
    _answering(monkeypatch, '{"keep":[]}')
    model = Model("")

    gatekeeping.worth_keeping(model, [Item("Newsletter", "Hi" + "͏ " * 200 + "Unsubscribe")])

    assert "͏" not in model.asked[0]
    assert "Unsubscribe" in model.asked[0]


# -- what a conversation proposes --------------------------------------------


def test_a_fact_worth_keeping_is_kept(monkeypatch) -> None:
    _answering(monkeypatch, "KEEP")

    assert gatekeeping.worth_remembering(Model(""), "Keyboards", "They own a Keychron K2")


def test_the_conversation_itself_is_not_a_memory(monkeypatch) -> None:
    """How "the user said hello" was written down five times."""
    _answering(monkeypatch, "DROP")

    assert not gatekeeping.worth_remembering(Model(""), "greeting", "The user said hello")


def test_a_proposed_memory_survives_a_gate_that_cannot_answer(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(gatekeeping.distil, "ask", boom)

    assert gatekeeping.worth_remembering(Model(""), "Keyboards", "They own a Keychron K2")
    assert gatekeeping.worth_remembering(None, "Keyboards", "They own a Keychron K2")
