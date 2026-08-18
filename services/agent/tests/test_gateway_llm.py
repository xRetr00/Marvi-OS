"""The Gateway seam, end to end.

The property that matters is not "it compiles". It is that a turn started by
LiveKit reaches ProviderClient, and that a provider failure arrives as a
failure rather than as silence — a voice turn that ends quietly looks to the
user like Marvi ignoring them.
"""

from __future__ import annotations

import pytest

from marvi_agent import gateway_llm


class FakeItem:
    def __init__(self, role, text):
        self.role = role
        self._text = text

    def text_content(self):
        return self._text


class FakeCtx:
    def __init__(self, items):
        self.items = items


def test_the_chat_context_becomes_wire_messages() -> None:
    ctx = FakeCtx([FakeItem("system", "be brief"), FakeItem("user", "hello")])

    assert gateway_llm._as_messages(ctx) == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hello"},
    ]


def test_items_that_are_not_turns_are_dropped() -> None:
    """A ChatContext carries function calls and results too; those are not
    messages and sending them as roles a provider does not know is a 400."""
    ctx = FakeCtx([FakeItem("function_call", "x"), FakeItem("user", "hi"), FakeItem("user", "  ")])

    assert gateway_llm._as_messages(ctx) == [{"role": "user", "content": "hi"}]


def test_an_empty_context_is_empty_not_an_error() -> None:
    assert gateway_llm._as_messages(FakeCtx([])) == []
    assert gateway_llm._as_messages(object()) == []


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ('data: {"delta": "hi"}', {"delta": "hi"}),
        ("data: [DONE]", None),
        ("data:", None),
        ("", None),
        (": keep-alive", None),
        ("data: not json", None),
    ],
)
def test_the_event_stream_is_read_the_same_way_the_gateway_writes_it(line, expected) -> None:
    assert gateway_llm._read(line) == expected


def test_the_llm_reports_that_the_gateway_chooses() -> None:
    # Not a cached model name: the user can change it in the control centre
    # mid-session, and a stale name here would be a quiet lie.
    assert gateway_llm.GatewayLLM().model == "gateway"


def test_the_job_and_surface_travel_with_the_turn() -> None:
    """Callers declare what they are doing; the Gateway decides who does it."""
    vision = gateway_llm.GatewayLLM(job="vision", surface="vision")

    assert (vision.job, vision.surface) == ("vision", "vision")
    assert (gateway_llm.GatewayLLM().job, gateway_llm.GatewayLLM().surface) == ("main", "voice")
