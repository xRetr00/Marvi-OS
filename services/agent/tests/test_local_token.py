"""Which token the Agent offers the Gateway, and what happens when it is stale.

`localauth.expected()` accepts the token the Gateway was started with *or* the
one on disk -- written for the case where the desktop adopts a Gateway from an
earlier launch. The Agent only ever offered the environment, which is a
snapshot taken when the worker started, so the mirror case was unhandled: a
worker that outlives its Gateway goes on presenting a token nothing accepts.

The log has it in bursts of four, one per retry, for the single endpoint that
hands out the provider credential:

    15:22 x4   15:23 x4   15:28 x4   15:49 x4   15:51 x4
    refused an unauthenticated request for /providers/voice
"""

from __future__ import annotations

import httpx
import pytest

from marvi_agent import runtime


@pytest.fixture(autouse=True)
def _elsewhere(tmp_path, monkeypatch):
    from marvi_agent import parakeet_stt

    monkeypatch.setattr(parakeet_stt, "APP_DATA", tmp_path)
    monkeypatch.delenv(runtime.LOCAL_TOKEN, raising=False)
    yield


def write_token(tmp_path, value: str) -> None:
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "state" / "local-token").write_text(value, encoding="utf-8")


def test_the_environment_comes_first(tmp_path, monkeypatch) -> None:
    # It is the better channel and stays primary: reading another process's
    # environment takes more than opening a file.
    monkeypatch.setenv(runtime.LOCAL_TOKEN, "from-the-launch")
    write_token(tmp_path, "on-disk")

    assert runtime.local_tokens() == ["from-the-launch", "on-disk"]
    assert runtime.local_token_header()["x-marvi-local"] == "from-the-launch"


def test_the_file_is_offered_when_there_is_no_environment(tmp_path) -> None:
    write_token(tmp_path, "on-disk")
    assert runtime.local_tokens() == ["on-disk"]


def test_the_same_token_twice_is_offered_once(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(runtime.LOCAL_TOKEN, "same")
    write_token(tmp_path, "same")
    assert runtime.local_tokens() == ["same"]


def test_no_token_anywhere_sends_no_header(tmp_path) -> None:
    # A developer running the Gateway by hand, or the eval harness. The guard
    # is not enforced there and requiring one would break every way of running
    # this outside the app.
    assert runtime.local_tokens() == []
    assert runtime.local_token_header() == {}


def test_a_stale_environment_token_falls_through_to_the_file(tmp_path, monkeypatch) -> None:
    """The worker outlived the Gateway that started it.

    The Gateway restarted twenty-nine times in one afternoon. A worker from an
    earlier launch presents that launch's token, gets 403, and voice is dead
    until the whole app is restarted -- which is what the bursts of four in the
    log are.
    """
    monkeypatch.setenv(runtime.LOCAL_TOKEN, "from-a-dead-gateway")
    write_token(tmp_path, "the-current-one")

    offered: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        token = request.headers.get("x-marvi-local", "")
        offered.append(token)
        if token != "the-current-one":
            return httpx.Response(403, json={"detail": "a local token is required"})
        return httpx.Response(
            200, json={"base_url": "http://localhost/v1", "model": "m", "api_key": "k"}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    config = runtime.AgentConfig._ask(client=client)

    assert offered == ["from-a-dead-gateway", "the-current-one"]
    assert config.model == "m"


def test_a_refusal_of_every_token_is_still_a_refusal(tmp_path, monkeypatch) -> None:
    # Falling back must not turn a real refusal into a hang or a silent
    # success; the message is what tells somebody to restart Marvi.
    monkeypatch.setenv(runtime.LOCAL_TOKEN, "wrong")
    write_token(tmp_path, "also-wrong")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "a local token is required"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        runtime.AgentConfig._ask(client=client)
