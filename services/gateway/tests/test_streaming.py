"""Streaming: three API modes, three envelopes.

Chat has never streamed — `call` hardcodes stream=False — so this is new
ground, and a wrong guess about an envelope would show up as a voice turn that
says nothing rather than as an exception. Hence a test per shape.
"""

from __future__ import annotations

import json

import pytest

from marvi_gateway.providers.base import ProviderProfile


def profile(mode: str) -> ProviderProfile:
    return ProviderProfile(name="p", api_mode=mode)  # type: ignore[arg-type]


def sse(payload: dict) -> str:
    return "data: " + json.dumps(payload)


# -- what every mode must ignore ---------------------------------------------


@pytest.mark.parametrize("mode", ["chat_completions", "responses", "anthropic"])
@pytest.mark.parametrize(
    "line",
    ["", "   ", ": keep-alive", "data: [DONE]", "data:", "event: ping", "data: not json"],
)
def test_noise_is_not_a_token(mode: str, line: str) -> None:
    # A keep-alive counted as a token would make first-token latency a lie.
    assert profile(mode).read_stream_line(line) is None


# -- chat completions --------------------------------------------------------


def test_chat_completions_delta() -> None:
    line = sse({"choices": [{"delta": {"content": "Hel"}}]})
    assert profile("chat_completions").read_stream_line(line) == {"delta": "Hel"}


def test_chat_completions_role_only_chunk_is_not_a_token() -> None:
    # The first chunk carries the role and no content.
    line = sse({"choices": [{"delta": {"role": "assistant"}}]})
    assert profile("chat_completions").read_stream_line(line) is None


def test_chat_completions_usage_arrives_without_choices() -> None:
    line = sse({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 4}})
    found = profile("chat_completions").read_stream_line(line)
    assert found is not None and found["usage"]["usage"]["prompt_tokens"] == 10


# -- anthropic ---------------------------------------------------------------


def test_anthropic_names_the_event_and_nests_the_text() -> None:
    line = sse({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hel"}})
    assert profile("anthropic").read_stream_line(line) == {"delta": "Hel"}


def test_anthropic_start_events_are_not_tokens() -> None:
    for kind in ("message_start", "content_block_start", "ping"):
        assert profile("anthropic").read_stream_line(sse({"type": kind})) is None


def test_anthropic_usage_comes_on_message_delta() -> None:
    line = sse({"type": "message_delta", "usage": {"output_tokens": 12}})
    found = profile("anthropic").read_stream_line(line)
    assert found is not None and found["usage"]["usage"]["output_tokens"] == 12


# -- responses ---------------------------------------------------------------


def test_responses_delta() -> None:
    line = sse({"type": "response.output_text.delta", "delta": "Hel"})
    assert profile("responses").read_stream_line(line) == {"delta": "Hel"}


def test_responses_other_events_are_not_tokens() -> None:
    for kind in ("response.created", "response.in_progress", "response.output_item.added"):
        assert profile("responses").read_stream_line(sse({"type": kind})) is None


def test_responses_usage_comes_on_completion() -> None:
    line = sse({"type": "response.completed", "response": {"usage": {"input_tokens": 7}}})
    found = profile("responses").read_stream_line(line)
    assert found is not None and found["usage"]["usage"]["input_tokens"] == 7


# -- the modes do not read each other ----------------------------------------


def test_a_mode_does_not_read_another_modes_envelope() -> None:
    """The failure this prevents is silent: a stream that yields nothing."""
    anthropic_line = sse({"type": "content_block_delta", "delta": {"text": "x"}})
    openai_line = sse({"choices": [{"delta": {"content": "x"}}]})

    assert profile("chat_completions").read_stream_line(anthropic_line) is None
    assert profile("anthropic").read_stream_line(openai_line) is None
