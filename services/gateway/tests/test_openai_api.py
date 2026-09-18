"""Marvi behind an OpenAI-shaped endpoint.

Everything that talks to a local model speaks this dialect, so answering it is
one adapter and a dozen programs work. What they reach is the whole assistant,
not a bare model -- which is also why it is behind the local guard.
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from marvi_gateway import openai_api


def test_the_newest_user_message_is_what_is_answered() -> None:
    messages = [
        {"role": "system", "content": "you are helpful"},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answered"},
        {"role": "user", "content": "  second  "},
    ]
    assert openai_api.last_user_message(messages) == "second"
    # The multimodal shape: the text parts, and nothing invented for the rest.
    assert (
        openai_api.last_user_message(
            [{"role": "user", "content": [{"type": "text", "text": "look"}, {"type": "image_url"}]}]
        )
        == "look"
    )
    assert openai_api.last_user_message([{"role": "assistant", "content": "x"}]) == ""
    assert openai_api.last_user_message("not a list") == ""


def test_one_conversation_per_caller() -> None:
    assert openai_api.thread_name("my-script") == "API · my-script"
    assert openai_api.thread_name("") == f"API · {openai_api.DEFAULT_USER}"


def test_the_shapes_clients_parse() -> None:
    whole = openai_api.completion("hello", tokens=7)
    assert whole["object"] == "chat.completion"
    assert whole["choices"][0]["message"] == {"role": "assistant", "content": "hello"}
    assert whole["choices"][0]["finish_reason"] == "stop"
    assert whole["usage"]["total_tokens"] == 7

    line = openai_api.chunk("hi")
    assert line.startswith("data: ") and line.endswith("\n\n")
    body = json.loads(line[len("data: ") :])
    assert body["object"] == "chat.completion.chunk"
    assert body["choices"][0]["delta"] == {"content": "hi"}
    assert body["choices"][0]["finish_reason"] is None

    last = json.loads(openai_api.chunk("", done=True)[len("data: ") :])
    assert last["choices"][0]["finish_reason"] == "stop" and last["choices"][0]["delta"] == {}


def test_a_stream_ends_with_done_and_never_leaks_reasoning() -> None:
    events = [
        {"reasoning": "the model thinking to itself"},
        {"delta": "Hel"},
        {"delta": "lo"},
        {"done": True, "tokens": 3},
    ]
    lines = list(openai_api.stream_lines(iter(events)))

    assert lines[-1].startswith("data: [DONE]")
    rendered = " ".join(lines)
    assert "thinking to itself" not in rendered
    assert json.loads(lines[0][len("data: ") :])["choices"][0]["delta"]["content"] == "Hel"
    # One id for the whole stream, which is what ties the chunks together.
    ids = {json.loads(line[len("data: ") :])["id"] for line in lines if "chatcmpl" in line}
    assert len(ids) == 1


def test_an_error_is_said_rather_than_dropped() -> None:
    lines = list(openai_api.stream_lines(iter([{"done": True, "error": "no provider"}])))
    assert "no provider" in " ".join(lines)
    assert lines[-1].startswith("data: [DONE]")


@pytest.mark.asyncio
async def test_the_endpoints_answer_and_are_guarded(monkeypatch, tmp_path) -> None:
    from marvi_gateway.app import create_app

    monkeypatch.setenv("MARVI_CHAT_DB", str(tmp_path / "chat.db"))
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        listed = await client.get("/v1/models")
        assert listed.status_code == 200
        assert listed.json()["data"][0]["id"] == "marvi"

        # A browser is refused, as it is on every credential-bearing route.
        from_page = await client.get("/v1/models", headers={"sec-fetch-site": "cross-site"})
        assert from_page.status_code == 403

        empty = await client.post("/v1/chat/completions", json={"messages": []})
        assert empty.status_code == 400

        # No provider is configured in tests, so the turn fails -- as an error
        # the client can read, not a hang or a 200 with nothing in it.
        answered = await client.post(
            "/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
        )
        assert answered.status_code == 502


@pytest.mark.asyncio
async def test_each_caller_keeps_its_own_conversation(monkeypatch, tmp_path) -> None:
    from marvi_gateway.chat import ChatStore

    store = ChatStore(tmp_path / "chat.db")
    first = store.thread_named(openai_api.thread_name("script-a"))
    again = store.thread_named(openai_api.thread_name("script-a"))
    other = store.thread_named(openai_api.thread_name("script-b"))

    assert first == again and first != other
    titles = {thread["title"] for thread in store.threads()}
    assert {"API · script-a", "API · script-b"} <= titles


def test_the_api_surface_has_a_brief() -> None:
    """The bug the unit tests missed and a real client found.

    `surface="api"` reads `prompts/api.md`; without it every call through the
    endpoint raised a 500 from deep inside the turn, while the tests passed
    because they never got that far.
    """
    from marvi_gateway import prompts

    brief = prompts.text("api", LANGUAGE="")
    assert "OpenAI-compatible endpoint" in brief
    # It must say the two things this surface cannot do.
    assert "widget" in brief.lower() and "confirmation" in brief.lower()
