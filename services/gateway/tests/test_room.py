"""Room sidecar tests.

These run a real newline-delimited JSON-RPC server on loopback rather than
patching the transport, so the framing, auth field, and failure modes are
exercised the same way the live runtime exercises them.
"""

from __future__ import annotations

import json
import socket
import threading

import pytest
from httpx import ASGITransport, AsyncClient

from marvi_gateway.app import create_app
from marvi_gateway.room import (
    NOTABLE_EVENTS,
    RoomRejectedError,
    RoomSidecar,
    RoomUnavailableError,
    faces,
    register_room_tools,
    unconfirmed,
    vision_preview,
)
from marvi_gateway.runtime import RuntimeStore
from marvi_gateway.tools import ToolRegistry

TOKEN = "test-rpc-token"


class FakeSidecar:
    """Minimal stand-in speaking the runtime's actual wire contract."""

    def __init__(self, home, responder=None):
        self.home = home
        self.requests: list[dict] = []
        self._responder = responder or self._default_responder
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(8)
        self.port = self._server.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        (home / ".rpc-token").write_text(TOKEN, encoding="utf-8")

    @staticmethod
    def _default_responder(request):
        method = request["method"]
        if method == "ping":
            return {"success": True}
        if method == "get_state":
            return {
                "success": True,
                "state": {"light": {"on": True}, "modes": {"active_mode": "focus"}},
            }
        if method == "get_health":
            return {"success": True, "health": {"devices": {"tuya_bulb": {"online": True}}}}
        if method in {"set_mode", "set_light"}:
            return {"success": True, "applied": request["params"]}
        return {"success": False, "error": f"unknown method: {method}"}

    def start(self):
        self._thread.start()
        return self

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            with conn:
                buffer = b""
                while b"\n" not in buffer:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    buffer += chunk
                if not buffer:
                    continue
                request = json.loads(buffer.decode("utf-8").strip())
                self.requests.append(request)
                if request.get("auth") != TOKEN:
                    payload = {"jsonrpc": "2.0", "id": request.get("id"), "error": "unauthorized"}
                else:
                    result = self._responder(request)
                    payload = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "result": {
                            "schema_version": 1,
                            "request_id": request.get("id"),
                            "status": "success" if result.get("success") else "failed",
                            **result,
                        },
                    }
                conn.sendall(json.dumps(payload).encode("utf-8") + b"\n")

    def stop(self):
        self._stop.set()
        self._server.close()
        self._thread.join(timeout=2)


@pytest.fixture
def sidecar(tmp_path):
    fake = FakeSidecar(tmp_path).start()
    client = RoomSidecar(port=fake.port, home=tmp_path, timeout=2.0)
    yield fake, client
    fake.stop()


def test_call_sends_the_authenticated_wire_contract(sidecar) -> None:
    fake, client = sidecar
    result = client.call("set_mode", {"mode": "focus"})

    assert result["success"] is True
    request = fake.requests[-1]
    assert request["jsonrpc"] == "2.0"
    assert request["auth"] == TOKEN
    assert request["method"] == "set_mode"
    assert request["params"] == {"mode": "focus"}
    assert request["id"]


def test_sidecar_refusal_is_a_decision_not_an_outage(sidecar) -> None:
    _, client = sidecar
    with pytest.raises(RoomRejectedError):
        client.call("no_such_method", {})


def test_missing_token_is_reported_as_unavailable(tmp_path) -> None:
    client = RoomSidecar(port=1, home=tmp_path, timeout=0.5)
    with pytest.raises(RoomUnavailableError):
        client.call("ping")


def test_dead_sidecar_is_unavailable_not_a_crash(sidecar) -> None:
    fake, client = sidecar
    fake.stop()

    assert client.reachable() is False
    with pytest.raises(RoomUnavailableError):
        client.call("ping")


def test_state_falls_back_to_the_disk_snapshot_while_the_sidecar_is_down(sidecar, tmp_path) -> None:
    fake, client = sidecar
    (tmp_path / "state.json").write_text(
        json.dumps({"light": {"on": False}, "modes": {"active_mode": "sleep"}}), encoding="utf-8"
    )
    live = client.state()
    fake.stop()
    stale = client.state()

    assert live["live"] is True
    assert live["state"]["modes"]["active_mode"] == "focus"
    assert stale["live"] is False
    assert stale["stale"] is True
    assert stale["state"]["modes"]["active_mode"] == "sleep"


def test_reconnect_after_restart_returns_to_live_reads(tmp_path) -> None:
    fake = FakeSidecar(tmp_path).start()
    client = RoomSidecar(port=fake.port, home=tmp_path, timeout=2.0)
    assert client.reachable() is True
    fake.stop()
    assert client.reachable() is False

    restarted = FakeSidecar(tmp_path)
    restarted._server.close()
    restarted._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    restarted._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    restarted._server.bind(("127.0.0.1", fake.port))
    restarted._server.listen(8)
    restarted.start()
    try:
        assert client.reachable() is True
        assert client.state()["live"] is True
    finally:
        restarted.stop()


@pytest.mark.asyncio
async def test_a_room_write_goes_straight_through_and_is_recorded(sidecar, tmp_path) -> None:
    """Confirmation is for actions that leave this machine and cannot be taken
    back. A light in your own room is local, reversible in one word, and yours
    -- and by voice, asking first turned "turn the light on" into a two-turn
    negotiation for no gain.

    What must not go is the record. The audit line is the accountability; the
    prompt was only ever friction.
    """
    fake, client = sidecar
    registry = ToolRegistry()
    register_room_tools(registry, client)
    runtime = RuntimeStore(audit_path=tmp_path / "audit.jsonl")
    app = create_app(version="0.1.0-test", runtime=runtime, tools=registry)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://marvi.local") as http:
        answer = await http.post(
            "/tools/room_set_light", json={"arguments": {"on": True, "brightness": 30}}
        )

    assert answer.json()["status"] == "executed"
    assert fake.requests[-1]["method"] == "set_light"
    assert fake.requests[-1]["params"] == {"on": True, "brightness": 30}
    assert "set_light" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_room_light_accepts_the_sidecars_rgb_contract(sidecar, tmp_path) -> None:
    fake, client = sidecar
    registry = ToolRegistry()
    register_room_tools(registry, client)
    app = create_app(
        version="0.1.0-test",
        runtime=RuntimeStore(audit_path=tmp_path / "audit.jsonl"),
        tools=registry,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://marvi.local") as http:
        answer = await http.post(
            "/tools/room_set_light",
            json={"arguments": {"on": True, "rgb": [255, 140, 42]}},
        )

    assert answer.json()["status"] == "executed"
    assert fake.requests[-1]["params"] == {"on": True, "rgb": [255, 140, 42]}


@pytest.mark.asyncio
async def test_room_read_is_not_gated_and_survives_sidecar_death(sidecar, tmp_path) -> None:
    fake, client = sidecar
    registry = ToolRegistry()
    register_room_tools(registry, client)
    runtime = RuntimeStore(audit_path=tmp_path / "audit.jsonl")
    app = create_app(version="0.1.0-test", runtime=runtime, tools=registry)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://marvi.local") as http:
        live = await http.post("/tools/room_state", json={"arguments": {}})
        fake.stop()
        dead = await http.post("/tools/room_state", json={"arguments": {}})
        still_serving = await http.get("/health")

    assert live.json()["status"] == "executed"
    assert dead.json()["status"] == "failed"
    assert "not reachable" in dead.json()["error"]
    assert still_serving.status_code == 200
    assert still_serving.json()["assistant"]["phase"] == "ready"


@pytest.mark.asyncio
async def test_invalid_room_arguments_never_reach_the_sidecar(sidecar, tmp_path) -> None:
    fake, client = sidecar
    registry = ToolRegistry()
    register_room_tools(registry, client)
    runtime = RuntimeStore(audit_path=tmp_path / "audit.jsonl")
    runtime.set_yolo(True)
    app = create_app(version="0.1.0-test", runtime=runtime, tools=registry)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://marvi.local") as http:
        bad_mode = await http.post(
            "/tools/room_set_mode", json={"arguments": {"mode": "self_destruct"}}
        )
        bad_brightness = await http.post(
            "/tools/room_set_light", json={"arguments": {"on": True, "brightness": 900}}
        )
        nonsense = await http.post("/tools/room_set_light", json={"arguments": {"on": "maybe"}})
        bad_rgb = await http.post(
            "/tools/room_set_light",
            json={"arguments": {"on": True, "rgb": [255, -1, 42]}},
        )

    assert bad_mode.json()["status"] == "failed"
    assert bad_brightness.json()["status"] == "failed"
    assert nonsense.status_code == 422
    assert bad_rgb.json()["status"] == "failed"
    assert [request["method"] for request in fake.requests] == []


# -- the event gap -------------------------------------------------------------


def _write_events(home, events) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8"
    )


def test_every_new_event_is_drained_not_just_the_newest(tmp_path) -> None:
    """Two notable things in one poll interval is not unusual.

    `latest_notable_event` returned one event per call and the Gateway called it
    once per health poll, so presence clearing and a light going off within the
    same two seconds meant one of them was never seen by anything.
    """
    home = tmp_path / "room"
    _write_events(
        home,
        [
            {"id": 1, "type": "mode_changed", "summary": "reading"},
            {"id": 2, "type": "presence_cleared", "summary": "empty"},
            {"id": 3, "type": "light_changed", "summary": "off"},
        ],
    )
    sidecar = RoomSidecar(home=home)

    fresh = sidecar.events_since(1)

    assert [event["id"] for event in fresh] == [2, 3]
    # Oldest first: these go into the journal, which records what happened in
    # the order it happened.
    assert [event["type"] for event in fresh] == ["presence_cleared", "light_changed"]


def test_nothing_is_returned_once_caught_up(tmp_path) -> None:
    home = tmp_path / "room"
    _write_events(home, [{"id": 7, "type": "light_changed", "summary": "on"}])

    assert RoomSidecar(home=home).events_since(7) == []


def test_a_cursor_of_none_returns_everything_notable(tmp_path) -> None:
    home = tmp_path / "room"
    _write_events(
        home,
        [
            {"id": 1, "type": "vision_identity_state", "summary": "ambient"},
            {"id": 2, "type": "light_changed", "summary": "on"},
        ],
    )

    fresh = RoomSidecar(home=home).events_since(None)

    # Ambient churn is still filtered; the cursor decides *when*, the allowlist
    # decides *what*.
    assert [event["id"] for event in fresh] == [2]


def test_the_allowlist_covers_what_the_engine_actually_writes() -> None:
    """Checked against two sources, because neither alone is complete.

    A real 500-event log says what the engine *has* emitted; its `_emit_event`
    calls say what it *can*. The first version of this list noticed four of the
    thirteen types in the log, and carried four names the engine has never
    emitted at all — `he20_occupied` and `he20_cleared` among them, which made a
    working mmwave sensor look broken.
    """
    for noticed in (
        "room_entry",
        "device_offline",
        "device_online",
        "phone_location_changed",
        "vision_sleep_state",
        # Surfaceable only because a held gesture is collapsed to one event.
        "vision_gesture",
    ):
        assert noticed in NOTABLE_EVENTS, noticed

    # Names the engine emits in neither its source nor a real log. The mmwave
    # sensor works; it reports through `presence_cleared` with source "mmwave".
    for invented in ("he20_occupied", "he20_cleared", "alarm_started", "alarm_cancelled"):
        assert invented not in NOTABLE_EVENTS, invented

    # Deliberately excluded: ambient state, and the engine's own bookkeeping.
    # `vision_identity_state` alone was 413 of those 500 events.
    for ignored in (
        "vision_identity_state",
        "smart_room_state_reconciled",
        "visitor_history_corrected",
    ):
        assert ignored not in NOTABLE_EVENTS, ignored


@pytest.mark.asyncio
async def test_a_stale_event_is_not_re_journaled_on_every_poll(tmp_path, monkeypatch) -> None:
    """The bug the cursor exists to fix.

    The Gateway appended whatever the newest room event was on *every* health
    poll. The journal's six-hour dedupe window was the only thing stopping a
    light change from yesterday re-entering the mind's queue — which it did,
    every six hours, forever.
    """
    from marvi_gateway.journal import EventJournal

    home = tmp_path / "room"
    _write_events(home, [{"id": 1, "type": "light_changed", "summary": "off"}])
    monkeypatch.setenv("MARVI_ROOM_HOME", str(home))
    monkeypatch.setenv("MARVI_JOURNAL_DB", str(tmp_path / "journal.sqlite3"))

    app = create_app(version="0.1.0-test")

    def room_events() -> list[dict]:
        journal = EventJournal(tmp_path / "journal.sqlite3")
        try:
            return [e for e in journal.recent(limit=100) if e["source"] == "room"]
        finally:
            journal.close()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://marvi.local"
    ) as client:
        for _ in range(4):
            await client.get("/runtime")

    # The first poll only established a baseline: nothing that predates Marvi
    # running is news, and nothing was appended four times.
    assert room_events() == []

    # A genuinely new event arrives, exactly once however often it is polled.
    _write_events(
        home,
        [
            {"id": 1, "type": "light_changed", "summary": "off"},
            {"id": 2, "type": "mode_changed", "summary": "reading"},
        ],
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://marvi.local"
    ) as client:
        for _ in range(3):
            await client.get("/runtime")

    recorded = room_events()
    assert len(recorded) == 1
    assert recorded[0]["kind"] == "mode_changed"


# -- not reporting a default as a reading -------------------------------------


#: One bulb exactly as the sidecar reports it.
#:
#: Every fixture below used to carry a `configured` key, which the sidecar has
#: never emitted -- the tests were written from the check rather than from a
#: payload, so they agreed with the bug instead of catching it. Copied from a
#: live `POST /tools/room_state` on 2026-08-28, when the room said the light
#: was not set up while it was on and had answered a poll five seconds before.
LIVE_BULB = {
    "online": True,
    "ip": "192.168.1.104",
    "last_seen": None,
    "last_poll": "2026-08-28T07:35:15.310431+00:00",
    "consecutive_failures": 0,
    "last_success": "2026-08-28T07:35:15.310431+00:00",
    "last_command": "get_status",
    "queue_depth": 0,
    "circuit_open": False,
}


def test_a_working_bulb_is_not_called_unconfigured() -> None:
    """The regression this file exists for now.

    The sidecar reported the bulb online, polled, and the light on and
    confirmed. `unconfirmed` read a `configured` flag off the device entry,
    got None because no such field is sent, and returned "say it is not set
    up" -- so Marvi told the user the light was not configured while they were
    sitting under it.
    """
    assert (
        unconfirmed(
            {
                "light": {"on": True, "brightness": 100, "scene": "custom", "confirmed": True},
                "devices": {"tuya_bulb": LIVE_BULB},
            }
        )
        == ""
    )


def test_a_light_with_no_bulb_at_all_is_not_reported_as_off() -> None:
    """The wrong answer that is worst: confident, specific, and about something
    the user is looking at.

    With no MQTT broker and no Tuya key the sidecar lists no bulb and `light`
    comes back as `{"on": false, "brightness": 0, "scene": "off",
    "confirmed": false}` -- a default, not a reading. Marvi passed it on as
    "the light is off" while it was on.
    """
    caveat = unconfirmed(
        {"light": {"on": False, "confirmed": False}, "devices": {"esp32": {"online": True}}}
    )

    assert "no light set up" in caveat
    assert "on or off" in caveat


def test_an_unreachable_light_says_so_rather_than_guessing() -> None:
    caveat = unconfirmed(
        {
            "light": {"on": True, "confirmed": True},
            "devices": {"tuya_bulb": {**LIVE_BULB, "online": False}},
        }
    )

    assert "unreachable" in caveat


def test_an_unconfirmed_reading_from_a_reachable_bulb_is_still_flagged() -> None:
    caveat = unconfirmed(
        {
            "light": {"on": True, "confirmed": False},
            "devices": {"tuya_bulb": LIVE_BULB},
        }
    )

    assert "unconfirmed" in caveat


@pytest.mark.asyncio
async def test_a_quoted_boolean_still_switches_the_light(sidecar, tmp_path) -> None:
    """Models writing JSON quote booleans, inconsistently, within one session.

    `{"on": "true"}` used to come back 422, so a spoken "turn the light on"
    failed on a punctuation choice the model made and the user could neither
    see nor correct. Nonsense is still refused - that is the test above.
    """
    fake, client = sidecar
    registry = ToolRegistry()
    register_room_tools(registry, client)
    runtime = RuntimeStore(audit_path=tmp_path / "audit.jsonl")
    runtime.set_yolo(True)
    app = create_app(version="0.1.0-test", runtime=runtime, tools=registry)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://marvi.local") as http:
        answer = await http.post("/tools/room_set_light", json={"arguments": {"on": "true"}})

    assert answer.json()["status"] == "executed"
    assert "set_light" in [request["method"] for request in fake.requests]


# -- the face library ---------------------------------------------------------


class FakeVision:
    """A sidecar with a face library, and nothing else."""

    def __init__(self, people=None, visitors=None, fails=()):
        self._people = people or []
        self._visitors = visitors or []
        self._fails = set(fails)

    def call(self, method, _params=None):
        if method in self._fails:
            raise RoomUnavailableError(f"{method} is not answering")
        if method == "vision_people":
            owner = next((p["name"] for p in self._people if p.get("owner")), "")
            return {"people": self._people, "owner": owner}
        if method == "vision_visitors":
            return {"visitors": self._visitors}
        if method == "vision_preview":
            return {
                "success": True,
                "preview": {
                    "available": True,
                    "image": "data:image/jpeg;base64,frame",
                },
            }
        raise AssertionError(method)


def test_the_owner_is_named_from_the_library() -> None:
    library = faces(FakeVision(people=[{"name": "Shereef", "owner": True, "samples": 8}]))

    assert library["ok"] is True
    assert library["owner"] == "Shereef"
    assert library["people"][0]["samples"] == 8


def test_vision_preview_uses_one_bounded_sidecar_frame() -> None:
    preview = vision_preview(FakeVision())

    assert preview == {
        "available": True,
        "image": "data:image/jpeg;base64,frame",
    }


def test_a_pending_sighting_carries_the_face_that_produced_it(tmp_path) -> None:
    """ "One unknown visitor" is not something anybody can act on. A face is."""
    crop = tmp_path / "visitor.jpg"
    crop.write_bytes(b"\xff\xd8\xff\xe0 not really a jpeg, but bytes")

    library = faces(
        FakeVision(visitors=[{"id": 4, "at": "2026-08-24T12:00:00", "thumbnail": str(crop)}])
    )

    assert library["pending"][0]["id"] == 4
    assert library["pending"][0]["image"].startswith("data:image/jpeg;base64,")


def test_a_thumbnail_that_is_gone_is_a_missing_picture_not_an_error() -> None:
    library = faces(FakeVision(visitors=[{"id": 5, "thumbnail": "C:/nowhere/gone.jpg"}]))

    assert library["ok"] is True
    assert library["pending"][0]["image"] == ""


def test_known_faces_still_show_when_the_pending_queue_cannot_be_read() -> None:
    """Half an answer beats none: who the camera knows does not depend on the
    review queue answering."""
    library = faces(
        FakeVision(
            people=[{"name": "Shereef", "owner": True, "samples": 8}],
            fails={"vision_visitors"},
        )
    )

    assert library["ok"] is True
    assert library["people"]
    assert library["pending"] == []


def test_an_unreachable_room_says_so_rather_than_looking_empty() -> None:
    """An empty library and an unreachable one look identical and mean
    opposite things."""
    library = faces(FakeVision(fails={"vision_people"}))

    assert library["ok"] is False
    assert "not answering" in library["detail"]


def test_a_pending_face_reaches_the_page_with_who_it_looks_like() -> None:
    """"34% nearest match" -- of whom?

    The review card could only show a score, so the one action it invited was
    typing a name the library already held. The sidecar knows who each pending
    face is closest to; this is the passthrough that lets the card say it.
    """
    library = faces(
        FakeVision(
            visitors=[
                {"id": 7, "score": 0.34, "nearest": {"name": "Shereef", "score": 0.3387}}
            ]
        )
    )

    assert library["pending"][0]["nearest"] == {"name": "Shereef", "score": 0.3387}


def test_a_pending_face_with_nobody_to_compare_against_says_so_quietly() -> None:
    """An empty library is not an error, and not a name either."""
    library = faces(FakeVision(visitors=[{"id": 8, "score": 0.0}]))

    assert library["pending"][0]["nearest"] == {}


@pytest.mark.asyncio
async def test_latency_can_be_read_back_not_only_written(tmp_path, monkeypatch) -> None:
    """Every timing number was recorded and none was ever read.

    Finding out that spoken replies had a p90 of 5.5 seconds against a 1.8
    second median took a regex over `agent.log`. The instrument existed; there
    was no way to ask it a question.
    """
    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    app = create_app(
        version="0.1.0-test", runtime=RuntimeStore(tmp_path / "r.db"), tools=ToolRegistry()
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://m.local") as c:
        for value in (900.0, 1000.0, 5500.0):
            posted = await c.post(
                "/latency",
                json={"surface": "voice", "path": "turn", "first_token_ms": value},
            )
            assert posted.status_code == 200
        summary = await c.get("/latency", params={"surface": "voice"})

    assert summary.status_code == 200
    body = summary.json()
    assert body["samples"] == 3
    group = next(g for g in body["groups"] if g["path"] == "turn")
    assert group["first_token_median_ms"] == 1000.0
