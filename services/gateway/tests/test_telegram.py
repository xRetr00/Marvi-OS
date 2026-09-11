"""Telegram as a surface.

Two kinds of test. The small ones pin the rules: only the linked owner is
answered, a link code works once, what other people wrote arrives enveloped,
the Mind texts only when the room was the problem. The last group runs the real
python-telegram-bot against a fake Bot API on loopback, with a real Chat turn
behind it, so the async plumbing -- polling, handlers, the worker-thread turn,
the reply, the Approve button -- is exercised across an actual HTTP boundary.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from marvi_gateway.chat import Chat, ChatStore
from marvi_gateway.journal import EventJournal
from marvi_gateway.mind import Mind
from marvi_gateway.policy import InitiativeSettings
from marvi_gateway.providers import ProviderClient
from marvi_gateway.schedule import LocalDelivery, ScheduleError
from marvi_gateway.telegram import (
    TelegramBridge,
    TelegramDelivery,
    TelegramUnavailableError,
    chunks,
    register_telegram_tools,
    telegram_html,
)
from marvi_gateway.tools import ToolRegistry

NOON = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
TOKEN = "123456789:" + "A" * 35
OWNER = 7


# -- formatting ------------------------------------------------------------------


def test_markdown_becomes_the_html_telegram_renders() -> None:
    html = telegram_html("**Done** — see [the docs](https://example.com/a?b=1&c=2) and `x<y`.")
    assert "<b>Done</b>" in html
    assert '<a href="https://example.com/a?b=1&amp;c=2">the docs</a>' in html
    assert "<code>x&lt;y</code>" in html


def test_what_the_model_writes_cannot_become_markup() -> None:
    assert telegram_html("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_code_blocks_and_tables_stay_readable() -> None:
    html = telegram_html("# Plan\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```py\nprint('**no**')\n```")
    assert "<b>Plan</b>" in html
    assert "<pre>| a | b |" in html
    assert "<pre>print('**no**')</pre>" in html


def test_long_replies_split_under_the_limit() -> None:
    text = "\n\n".join("word " * 300 for _ in range(10))
    parts = chunks(text, limit=3500)
    assert len(parts) > 1
    assert all(len(part) <= 3500 for part in parts)
    assert "".join(parts).replace("\n", "").replace(" ", "") == text.replace("\n", "").replace(" ", "")


def test_a_voice_note_becomes_the_pcm_the_recogniser_takes() -> None:
    """Telegram sends OGG/Opus; the dictation worker wants 16 kHz mono PCM16."""
    import io

    import av
    import numpy as np

    buffer = io.BytesIO()
    with av.open(buffer, "w", format="ogg") as container:
        stream = container.add_stream("libopus", rate=48_000, layout="mono")
        tone = (np.sin(np.arange(48_000) * 2 * np.pi * 440 / 48_000) * 8000).astype(np.int16)
        frame = av.AudioFrame.from_ndarray(tone.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = 48_000
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)

    from marvi_gateway.telegram import pcm16_from_audio

    pcm = pcm16_from_audio(buffer.getvalue())
    seconds = len(pcm) / (16_000 * 2)
    assert 0.9 < seconds < 1.2


# -- pairing and the one owner ------------------------------------------------------


def connected(tmp_path: Path, **kwargs: Any) -> TelegramBridge:
    bridge = TelegramBridge(
        SimpleNamespace(store=ChatStore(tmp_path / "chat.sqlite3")),
        state_path=tmp_path / "telegram.json",
        **kwargs,
    )
    bridge._app = SimpleNamespace(bot=SimpleNamespace(username="marvi_bot", first_name="Marvi"))
    bridge._phase = "ready"
    return bridge


def person(user_id: int = OWNER) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, first_name="Sam", last_name=None, username="sam")


def test_a_link_code_works_once(tmp_path) -> None:
    bridge = connected(tmp_path)
    code = bridge.pair()["code"]

    assert bridge.claim("WRONGONE", person()) is False
    assert bridge.claim(code.lower(), person()) is True
    assert bridge.is_owner(OWNER)
    assert bridge.claim(code, person(99)) is False, "a used code links nobody else"
    assert not bridge.is_owner(99)


def test_the_link_comes_as_a_qr_code_for_the_phone(tmp_path) -> None:
    """`t.me` on a PC needs Telegram Desktop; a phone camera needs nothing."""
    pairing = connected(tmp_path).pair()
    assert pairing["link"].startswith("https://t.me/marvi_bot?start=")
    assert pairing["qr"].startswith("data:image/svg+xml")


def test_telegram_threads_are_marked_and_never_the_windows_default(tmp_path) -> None:
    store = ChatStore(tmp_path / "chat.sqlite3")
    store.delete_thread(store.threads()[0]["id"])  # only a phone thread will remain
    phone = store.create_thread("Sam", channel="telegram")
    assert store.get_thread(phone["id"])["channel"] == "telegram"
    assert store.resolve("default") != phone["id"]


def test_an_expired_code_links_nobody(tmp_path) -> None:
    bridge = connected(tmp_path)
    code = bridge.pair()["code"]
    bridge._pairing = (code, time.time() - 1)
    assert bridge.claim(code, person()) is False
    assert bridge.owner is None


def test_the_owner_survives_a_restart(tmp_path) -> None:
    bridge = connected(tmp_path)
    assert bridge.claim(bridge.pair()["code"], person())
    again = connected(tmp_path)
    assert again.is_owner(OWNER)
    again.unlink()
    assert connected(tmp_path).owner is None


def test_the_status_never_hands_the_model_a_link_code(tmp_path) -> None:
    bridge = connected(tmp_path)
    bridge.pair()
    registry = ToolRegistry()
    register_telegram_tools(registry, bridge)
    spec = registry.get("telegram_status")
    assert "pairing" not in registry.execute(spec, {})


def test_sending_needs_a_linked_owner(tmp_path) -> None:
    bridge = connected(tmp_path)
    with pytest.raises(TelegramUnavailableError, match="linked"):
        bridge.send("hello")


# -- files ---------------------------------------------------------------------------------


def jpeg(path: Path, stamp: float) -> Path:
    import os

    path.write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 64)
    os.utime(path, (stamp, stamp))
    return path


def test_a_folder_sends_its_newest_photos(tmp_path) -> None:
    """The failure in the logs: a folder of visitor photos was 'not a file'."""
    from marvi_gateway.telegram import pick_files

    visits = tmp_path / "visits"
    visits.mkdir()
    for index in range(12):
        jpeg(visits / f"visit-{index:02}.jpg", 1_000 + index)
    (visits / "visit.json").write_text("{}")

    chosen, left = pick_files([visits])

    assert [p.name for p in chosen][:2] == ["visit-11.jpg", "visit-10.jpg"]
    assert len(chosen) == 10 and left == 2
    assert all(p.suffix == ".jpg" for p in chosen), "metadata stays behind when there are photos"


def test_named_files_are_checked_before_anything_is_sent(tmp_path) -> None:
    from marvi_gateway.telegram import pick_files

    with pytest.raises(ValueError, match="does not exist"):
        pick_files([tmp_path / "nope.jpg"])
    (tmp_path / "empty").mkdir()
    with pytest.raises(ValueError, match="empty folder"):
        pick_files([tmp_path / "empty"])


# -- cron delivery -----------------------------------------------------------------------


class FakeBridge:
    def __init__(self, linked: bool = True) -> None:
        self.sent: list[tuple[str, str]] = []
        self._linked = linked

    def linked(self) -> bool:
        return self._linked

    def send(self, text: str, file: Any = None, origin: str = "") -> dict[str, Any]:
        if not self._linked:
            raise TelegramUnavailableError("no Telegram account is linked yet")
        self.sent.append((text, origin))
        return {"sent": True}


def test_cron_output_can_go_to_telegram() -> None:
    bridge = FakeBridge()
    delivery = TelegramDelivery(bridge)  # type: ignore[arg-type]

    assert {"id": "telegram", "name": "Telegram (your phone)", "available": True} in delivery.targets()
    outcome = delivery.deliver("telegram", "All clear.", {"schedule_id": 3, "name": "Inbox check"})

    assert outcome == "sent_telegram"
    assert bridge.sent == [("**Inbox check**\n\nAll clear.", "cron:3")]
    assert delivery.deliver("local", "x", {}) == LocalDelivery().deliver("local", "x", {})


def test_a_failed_telegram_delivery_fails_the_run_visibly() -> None:
    delivery = TelegramDelivery(FakeBridge(linked=False))  # type: ignore[arg-type]
    with pytest.raises(ScheduleError, match="Telegram delivery failed"):
        delivery.deliver("telegram", "x", {"name": "job"})


# -- the Mind ---------------------------------------------------------------------------------


@pytest.fixture
def journal(tmp_path):
    j = EventJournal(tmp_path / "journal.sqlite3")
    yield j
    j.close()


class Waiting:
    def __init__(self) -> None:
        self.held: list[str] = []

    def hold(self, event: dict[str, Any], rule: str) -> None:
        self.held.append(rule)

    def release(self, _test: Any) -> list[Any]:
        return []


def a_mind(journal, texted: list[str], answer: bool = True) -> Mind:
    mind = Mind(journal, settings=InitiativeSettings(quiet_enabled=False))
    mind.waiting = Waiting()

    def messenger(sentence: str, event: dict[str, Any]) -> bool:
        texted.append(sentence)
        return answer

    mind.messenger = messenger
    return mind


def test_nobody_home_means_a_text_instead_of_speech(journal) -> None:
    texted: list[str] = []
    mind = a_mind(journal, texted)
    journal.append("schedule", "reminder", "Take the bins out", {"id": "r1"}, trusted=True)

    result = mind.tick(now=NOON, present=False)

    assert texted, "the reminder reached the phone"
    assert result["decisions"][0]["rule"] == "nobody-present"
    assert mind.waiting.held == [], "and is not also held to be said aloud later"
    assert journal.decisions(limit=1)[0]["outcome"].startswith("texted: ")


def test_a_text_that_fails_is_held_as_before(journal) -> None:
    texted: list[str] = []
    mind = a_mind(journal, texted, answer=False)
    journal.append("schedule", "reminder", "Take the bins out", {"id": "r2"}, trusted=True)

    mind.tick(now=NOON, present=False)

    assert mind.waiting.held == ["nobody-present"]


def test_someone_home_means_no_text(journal) -> None:
    texted: list[str] = []
    mind = a_mind(journal, texted)
    journal.append("schedule", "reminder", "Stretch", {"id": "r3"}, trusted=True)

    mind.tick(now=NOON, present=True)

    assert texted == []


# -- the Chat turn knows it is on Telegram ------------------------------------------------------


def sse(*lines: str) -> str:
    return "".join(f"data: {line}\n" for line in [*lines, "[DONE]"])


ANSWER = sse(
    '{"choices":[{"delta":{"content":"On it — "}}]}',
    '{"choices":[{"delta":{"content":"**done**."}}]}',
    '{"usage":{"prompt_tokens":10,"completion_tokens":4}}',
)


def recording_chat(tmp_path: Path, seen: list[dict[str, Any]]) -> Chat:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, text=ANSWER, headers={"content-type": "text/event-stream"})

    return Chat(
        store=ChatStore(tmp_path / "chat.sqlite3"),
        client=ProviderClient(http=httpx.Client(transport=httpx.MockTransport(handler))),
    )


def test_a_telegram_turn_gets_the_telegram_brief_and_no_widgets(tmp_path, configured) -> None:
    configured()
    seen: list[dict[str, Any]] = []
    chat = recording_chat(tmp_path, seen)

    list(chat.send_stream("hi", surface="telegram"))
    list(chat.send_stream("hi"))

    telegram, window = seen
    assert "answering the user on Telegram" in telegram["messages"][0]["content"]
    assert "typed chat window" in window["messages"][0]["content"]
    names = lambda body: {t["function"]["name"] for t in body.get("tools") or []}  # noqa: E731
    assert "present_widget" not in names(telegram)
    assert "present_widget" in names(window)


# -- the Gateway routes ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_gateway_publishes_telegram_behind_the_local_token(monkeypatch) -> None:
    from httpx import ASGITransport, AsyncClient

    from marvi_gateway.app import create_app

    transport = ASGITransport(app=create_app(version="0.1.0-test"))
    async with AsyncClient(transport=transport, base_url="http://marvi.local") as client:
        page = (await client.get("/telegram")).json()
        assert page["configured"] is False and page["state"] == "off"

        tools = {t["name"] for t in (await client.get("/tools")).json()["tools"]}
        assert {"telegram_send", "telegram_status", "telegram_recent"} <= tools

        targets = (await client.get("/schedules")).json()["delivery_targets"]
        assert {"id": "telegram", "name": "Telegram (your phone)", "available": False} in targets

        refused = await client.put("/telegram/token", json={"token": "not-a-token"})
        assert refused.status_code == 400 and "BotFather" in refused.json()["detail"]
        assert (await client.post("/telegram/pair")).status_code == 409

        # Linking decides who can command Marvi from anywhere, so a local
        # process without the desktop's token gets nothing.
        monkeypatch.setenv("MARVI_LOCAL_TOKEN", "desktop-secret")
        assert (await client.get("/telegram")).status_code == 403
        assert (await client.post("/telegram/pair")).status_code == 403
        allowed = await client.get("/telegram", headers={"x-marvi-local": "desktop-secret"})
        assert allowed.status_code == 200


# -- the real SDK against a fake Bot API ------------------------------------------------------------


class FakeTelegram:
    """Just enough of the Bot API for python-telegram-bot to run against."""

    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.uploads: list[tuple[str, list[str], dict[str, Any]]] = []
        self.next_update = 1
        self.next_message = 100
        self.lock = threading.Lock()

    def push(self, **update: Any) -> None:
        with self.lock:
            self.updates.append({"update_id": self.next_update, **update})
            self.next_update += 1

    def text(self, text: str, user_id: int = OWNER) -> None:
        entities = (
            [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
            if text.startswith("/")
            else []
        )
        self.push(message={
            "message_id": self.next_update, "date": int(time.time()),
            "chat": {"id": user_id, "type": "private", "first_name": "Sam"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Sam"},
            "text": text, "entities": entities,
        })

    def tap(self, data: str, user_id: int = OWNER) -> None:
        self.push(callback_query={
            "id": f"cb{self.next_update}", "chat_instance": "x", "data": data,
            "from": {"id": user_id, "is_bot": False, "first_name": "Sam"},
            "message": {"message_id": 1, "date": int(time.time()),
                        "chat": {"id": user_id, "type": "private"}, "text": "card"},
        })

    def said(self, method: str = "sendMessage") -> list[str]:
        return [str(params.get("text", "")) for name, params in self.calls if name == method]

    async def handle(self, request: Request) -> Response:
        method = request.path_params["method"]
        form = await request.form()
        params = {key: value for key, value in form.items() if isinstance(value, str)}
        with self.lock:
            self.calls.append((method, params))
        if method == "getMe":
            return self.ok({"id": 42, "is_bot": True, "first_name": "Marvi",
                            "username": "marvi_test_bot"})
        if method == "getUpdates":
            offset = int(params.get("offset") or 0)
            for _ in range(10):
                with self.lock:
                    fresh = [u for u in self.updates if u["update_id"] >= offset]
                if fresh:
                    return self.ok(fresh)
                await asyncio.sleep(0.05)
            return self.ok([])
        uploads = [value.filename for value in form.values() if not isinstance(value, str)]
        if uploads:
            with self.lock:
                self.uploads.append((method, uploads, params))
        if method in ("sendMessage", "editMessageText", "sendPhoto", "sendDocument"):
            return self.ok(self.message(params))
        if method == "sendMediaGroup":
            return self.ok([self.message(params) for _ in uploads])
        return self.ok(True)

    def message(self, params: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self.next_message += 1
            number = self.next_message
        return {"message_id": number, "date": int(time.time()),
                "chat": {"id": int(params.get("chat_id") or OWNER), "type": "private"},
                "text": params.get("text", "")}

    @staticmethod
    def ok(result: Any) -> Response:
        return JSONResponse({"ok": True, "result": result})


@pytest.fixture
def fake_telegram():
    fake = FakeTelegram()
    app = Starlette(routes=[Route("/bot{token}/{method}", fake.handle, methods=["GET", "POST"])])
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    # `log_config=None`: uvicorn otherwise reconfigures its loggers process-wide,
    # and every test after this one saw `uvicorn.error` stuck at WARNING.
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, access_log=False)
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)
    fake.url = f"http://127.0.0.1:{port}"
    yield fake
    server.should_exit = True
    thread.join(timeout=5)


async def until(check: Any, seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("timed out waiting for the bot")


@pytest.mark.asyncio
async def test_link_talk_and_approve_over_the_real_sdk(
    tmp_path, fake_telegram, monkeypatch, configured
) -> None:
    configured()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    settled: list[tuple[str, bool]] = []

    def settle(token: str, approve: bool) -> dict[str, Any]:
        settled.append((token, approve))
        return {"status": "executed", "tool": "room_set_light", "arguments": {"on": True},
                "result": {"light": "on"}}

    chat = recording_chat(tmp_path, [])
    bridge = TelegramBridge(
        chat, settle=settle, state_path=tmp_path / "telegram.json", base_url=fake_telegram.url
    )
    await bridge.start()
    try:
        await until(bridge.ready)
        await until(lambda: bridge.state.data.get("profile"))
        assert any(name == "setMyCommands" for name, _ in fake_telegram.calls)

        # A stranger, before anyone is linked, is told how linking works.
        fake_telegram.text("hello?", user_id=99)
        await until(lambda: any("only talk" in s for s in fake_telegram.said()))

        # The owner links with the code the desktop showed.
        code = bridge.pair()["code"]
        fake_telegram.text(f"/start {code}")
        await until(lambda: bridge.owner is not None)
        await until(lambda: any("Linked" in s for s in fake_telegram.said()))

        # A message becomes a Chat turn, and the answer comes back formatted.
        fake_telegram.text("turn the light on")
        await until(lambda: any("<b>done</b>" in s for s in fake_telegram.said()))
        thread = bridge.status()["thread_id"]
        assert [r["role"] for r in chat.store.history(thread_id=thread)] == ["user", "assistant"]
        assert chat.store.get_thread(thread)["channel"] == "telegram"

        # Approve goes through the Gateway's confirmation path, then she carries on.
        before = len(fake_telegram.said())
        fake_telegram.tap("cf:a:TOKEN123")
        await until(lambda: settled == [("TOKEN123", True)])
        await until(lambda: any("Approved" in s for s in fake_telegram.said("editMessageText")))
        await until(lambda: len(fake_telegram.said()) > before)
        roles = [r["role"] for r in chat.store.history(thread_id=thread)]
        assert roles[-3:] == ["tool", "user", "assistant"]

        # Someone else pressing the owner's button is refused.
        fake_telegram.tap("cf:a:OTHER", user_id=99)
        await asyncio.sleep(0.5)
        assert ("OTHER", True) not in settled
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_files_reach_the_phone_as_an_album_a_photo_and_a_document(
    tmp_path, fake_telegram, monkeypatch, configured
) -> None:
    """Through the tool the model calls, over the real SDK, to a Bot API."""
    configured()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    state = tmp_path / "telegram.json"
    state.write_text(json.dumps({"owner": {"id": OWNER, "name": "Sam"}, "threads": {}}))
    visits = tmp_path / "visits"
    visits.mkdir()
    for index in range(3):
        jpeg(visits / f"v{index}.jpg", 1_000 + index)
    notes = tmp_path / "notes.txt"
    notes.write_text("hello")

    bridge = TelegramBridge(
        recording_chat(tmp_path, []), state_path=state, base_url=fake_telegram.url,
        workspace=SimpleNamespace(resolve=lambda name: Path(name)),
    )
    registry = ToolRegistry()
    register_telegram_tools(registry, bridge)
    send = registry.get("telegram_send")
    await bridge.start()
    try:
        await until(bridge.ready)
        album = await asyncio.to_thread(
            registry.execute, send, {"text": "Today's visitors", "file": str(visits)}
        )
        assert album["files"] == ["v2.jpg", "v1.jpg", "v0.jpg"]
        await asyncio.to_thread(registry.execute, send, {"files": [str(visits / "v0.jpg")]})
        await asyncio.to_thread(registry.execute, send, {"text": "notes", "files": [str(notes)]})

        sent = [(method, len(names)) for method, names, _ in fake_telegram.uploads
                if method != "setMyProfilePhoto"]
        assert sent == [("sendMediaGroup", 3), ("sendPhoto", 1), ("sendDocument", 1)]
        media = json.loads(next(p for m, _, p in fake_telegram.uploads if m == "sendMediaGroup")["media"])
        assert media[0]["caption"] == "Today's visitors"
        assert "caption" not in media[1]
    finally:
        await bridge.stop()
