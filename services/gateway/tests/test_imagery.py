"""Drawing a picture, and getting it into the conversation.

The second half is the one that kept this unbuilt: a tool handler does not know
which thread it is running in, so a generated image had nowhere to go. The
contract is `{"produced": {...}}` and `chat._keep_produced` places it.
"""

from __future__ import annotations

import base64
import io as _io

import httpx
import pytest
from PIL import Image

from marvi_gateway import imagery
from marvi_gateway.chat import Chat, ChatStore
from marvi_gateway.tools import ToolRegistry


def _png(colour: str = "white") -> bytes:
    buffer = _io.BytesIO()
    Image.new("RGB", (8, 8), colour).save(buffer, "PNG")
    return buffer.getvalue()


class FakeClient:
    """A provider that answers the images endpoint."""

    def __init__(self, handler) -> None:
        self.http = httpx.Client(transport=httpx.MockTransport(handler))

    def candidates(self, preferred=None):
        from marvi_gateway.providers import get

        return [get("openai")]

    def _client(self):
        return self.http

    def key_index(self, _name: str) -> int:
        return 0


@pytest.fixture
def configured_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.delenv("MARVI_LOCAL_ONLY", raising=False)
    monkeypatch.setenv("MARVI_PRIVACY_MODE", "0")


def test_it_asks_the_images_endpoint_and_returns_the_bytes(configured_openai) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.read().decode()
        return httpx.Response(
            200, json={"data": [{"b64_json": base64.b64encode(_png()).decode()}]}
        )

    made = imagery.generate(FakeClient(handler), "a small white square")

    assert seen["url"].endswith("/images/generations")
    assert "a small white square" in seen["body"] and "1024x1024" in seen["body"]
    with Image.open(_io.BytesIO(made["data"])) as image:
        assert image.format == "PNG"


def test_a_gateway_that_answers_with_a_url_is_followed(configured_openai) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/images/generations"):
            return httpx.Response(200, json={"data": [{"url": "https://pictures.test/a.png"}]})
        return httpx.Response(200, content=_png("black"))

    assert imagery.generate(FakeClient(handler), "a square")["data"][:4] == _png("black")[:4]


def test_local_only_and_a_missing_provider_are_said_plainly(monkeypatch) -> None:
    monkeypatch.setenv("MARVI_LOCAL_ONLY", "1")
    with pytest.raises(imagery.ImageUnavailableError, match="local-only"):
        imagery.generate(FakeClient(lambda _r: httpx.Response(200, json={})), "x")

    monkeypatch.setenv("MARVI_LOCAL_ONLY", "0")

    class NoProviders:
        def candidates(self, preferred=None):
            return []

    with pytest.raises(imagery.ImageUnavailableError, match="Settings > Providers"):
        imagery.generate(NoProviders(), "x")


def test_a_refused_request_is_an_error_not_an_exception(configured_openai) -> None:
    registry = ToolRegistry()
    imagery.register_image_tools(
        registry,
        FakeClient(lambda _r: httpx.Response(429, text="slow down")),
    )
    result = registry.execute(registry.get("image_generate"), {"prompt": "a cat"})
    assert "429" in result["error"] and "made" not in result


def test_the_picture_becomes_an_attachment_on_the_conversation(tmp_path, configured_openai) -> None:
    """The contract, end to end: tool makes bytes, the thread gets a file."""
    store = ChatStore(tmp_path / "chat.db")
    thread = store.create_thread("Drawing")["id"]
    talk = Chat(store=store)

    produced = talk._keep_produced(
        "image_generate",
        {
            "produced": {
                "name": "a-cat.png",
                "media_type": "image/png",
                "data": base64.b64encode(_png()).decode(),
            }
        },
        thread,
    )

    assert produced["type"] == "attachment" and produced["name"] == "a-cat.png"
    rows = store.pending_attachments(thread, [produced["attachment_id"]])
    assert rows[0]["media_type"] == "image/png" and rows[0]["size"] > 0


def test_a_result_with_no_file_changes_nothing(tmp_path) -> None:
    store = ChatStore(tmp_path / "chat.db")
    thread = store.create_thread("Plain")["id"]
    talk = Chat(store=store)

    assert talk._keep_produced("web_search", {"results": []}, thread) is None
    assert talk._keep_produced("web_search", "a string", thread) is None
    # Bad base64 is a tool's mistake, not a failed turn.
    assert talk._keep_produced("x", {"produced": {"data": "not base64!!"}}, thread) is None
