"""How a tool call and its result are put back on the wire.

Every provider documents the same round trip: the assistant message that asked
for the tool goes back with its `tool_calls`, and each result returns as its own
message carrying the `tool_call_id` it answers. Marvi replayed neither. It sent
the result alone, as an observation with no author, so the model saw an answer
to a question it had no record of asking.

The three APIs spell it differently, which is the reason `build_request` exists,
so the neutral shape is assembled once and translated per provider.

Sources: OpenRouter's tool-calling guide and OpenAI's function-calling guide.
"""

from __future__ import annotations

import json

import httpx

from marvi_gateway.chat import Chat, ChatStore
from marvi_gateway.providers import ProviderClient, get


def sse(*lines: str) -> str:
    return "".join(f"data: {line}\n" for line in [*lines, "[DONE]"])


CALL = sse(
    '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_abc123",'
    '"function":{"name":"set_light","arguments":"{\\"on\\":true}"}}]}}]}'
)
ANSWER = sse('{"choices":[{"delta":{"content":"Done."}}]}')


def rounds(bodies: list, *replies: str) -> httpx.Client:
    seen = iter(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200, text=next(seen), headers={"content-type": "text/event-stream"}
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def run(tmp_path, bodies, dispatch=None):
    chat = Chat(
        store=ChatStore(tmp_path / "chat.sqlite3"),
        client=ProviderClient(http=rounds(bodies, CALL, ANSWER)),
        dispatch=dispatch or (lambda name, arguments: {"status": "executed", "result": "on"}),
    )
    return list(chat.send_stream("turn the light on"))


def test_the_assistant_message_that_asked_goes_back(tmp_path, configured) -> None:
    configured()
    bodies: list = []
    run(tmp_path, bodies)

    asked = [m for m in bodies[1]["messages"] if m.get("tool_calls")]

    assert asked, "the model was not shown the call it made"
    call = asked[0]["tool_calls"][0]
    assert call["id"] == "call_abc123"
    assert call["type"] == "function"
    assert call["function"]["name"] == "set_light"
    assert json.loads(call["function"]["arguments"]) == {"on": True}


def test_the_result_answers_its_call_by_id(tmp_path, configured) -> None:
    configured()
    bodies: list = []
    run(tmp_path, bodies)

    results = [m for m in bodies[1]["messages"] if m.get("role") == "tool"]

    assert results, "the result did not come back as a tool message"
    assert results[0]["tool_call_id"] == "call_abc123"
    assert "on" in results[0]["content"]


def test_a_tool_that_failed_says_so(tmp_path, configured) -> None:
    """The model was told `null` and could not tell that from an empty result.

    So it could not correct a bad argument, and it could report an action as
    done when the tool had refused it.
    """
    configured()
    bodies: list = []
    run(
        tmp_path,
        bodies,
        dispatch=lambda name, arguments: {
            "status": "failed",
            "error": "no such device 'kitchen'",
        },
    )

    results = [m for m in bodies[1]["messages"] if m.get("role") == "tool"]
    said = results[0]["content"]

    assert "no such device" in said, f"the failure was not reported: {said!r}"
    assert "null" not in said


def test_anthropic_gets_content_blocks(tmp_path, configured) -> None:
    """Anthropic spells the same round trip as `tool_use` / `tool_result`."""
    profile = get("anthropic")
    body = profile.build_request(
        [
            {"role": "user", "content": "light on"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {"name": "set_light", "arguments": '{"on":true}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_abc123", "content": "on"},
        ],
        model="claude",
    )

    assistant = next(m for m in body["messages"] if m["role"] == "assistant")
    use = assistant["content"][0]
    assert use["type"] == "tool_use"
    assert use["id"] == "call_abc123"
    assert use["name"] == "set_light"
    assert use["input"] == {"on": True}

    result = body["messages"][-1]["content"][0]
    assert result["type"] == "tool_result"
    assert result["tool_use_id"] == "call_abc123"


def test_the_responses_api_gets_function_call_items(tmp_path, configured) -> None:
    """The Responses API spells it as `function_call` / `function_call_output`."""
    profile = get("openai-responses")
    body = profile.build_request(
        [
            {"role": "user", "content": "light on"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {"name": "set_light", "arguments": '{"on":true}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_abc123", "content": "on"},
        ],
        model="gpt",
    )

    kinds = [i.get("type") for i in body["input"] if isinstance(i, dict)]
    assert "function_call" in kinds
    assert "function_call_output" in kinds
    call = next(i for i in body["input"] if i.get("type") == "function_call")
    assert call["call_id"] == "call_abc123"
    assert call["name"] == "set_light"
