from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from marvi_gateway.app import create_app
from marvi_gateway.room import NOTABLE_EVENTS, RoomSidecar, summarize_event
from marvi_gateway.runtime import ROOM_EVENT_TTL_SECONDS, RuntimeStore
from marvi_gateway.tools import ToolRegistry

AMBIENT = {
    "id": 1,
    "at": "2026-08-16T03:40:47Z",
    "type": "vision_identity_state",
    "summary": "vision identity state",
}
NOTABLE = {
    "id": 2,
    "at": "2026-08-16T03:41:00Z",
    "type": "mode_changed",
    "summary": "mode changed to sleep",
}
VISITOR = {
    "id": 3,
    "at": "2026-08-16T03:42:00Z",
    "type": "room_presence_unverified",
    "summary": "unverified entry",
}


def write_events(home, events) -> None:
    (home / "events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8"
    )


def test_summaries_carry_the_detail_the_sidecar_label_omits() -> None:
    # Real payloads: the sidecar's own summary is just the type label.
    assert (
        summarize_event(
            {"type": "mode_changed", "mode": "focus", "source": "manual", "summary": "mode changed"}
        )
        == "Mode changed to focus (manual)"
    )
    assert (
        summarize_event(
            {
                "type": "light_changed",
                "on": True,
                "brightness": 100,
                "color_temp": 6500,
                "source": "manual",
                "summary": "light changed",
            }
        )
        == "Light on at 100% 6500K (manual)"
    )
    assert (
        summarize_event({"type": "light_changed", "on": False, "source": "automation"})
        == "Light off (automation)"
    )
    assert (
        summarize_event(
            {"type": "room_presence_unverified", "identity_reason": "stale_owntracks"}
        )
        == "Unverified entry: stale_owntracks"
    )


def test_unknown_event_types_fall_back_to_the_sidecar_summary() -> None:
    assert summarize_event({"type": "alarm_started", "summary": "alarm started"}) == "Alarm started"
    assert summarize_event({"type": "future_event"}) == "Future_event"


def test_bursty_gesture_events_are_not_notable() -> None:
    assert "vision_gesture" not in NOTABLE_EVENTS


def test_ambient_vision_churn_is_filtered_out(tmp_path) -> None:
    write_events(tmp_path, [AMBIENT] * 400 + [NOTABLE])
    sidecar = RoomSidecar(port=1, home=tmp_path)

    assert [event["type"] for event in sidecar.events()] == ["mode_changed"]
    assert len(sidecar.events(notable_only=False)) > 1


def test_events_are_newest_first_and_survive_a_truncated_tail(tmp_path) -> None:
    write_events(tmp_path, [NOTABLE, VISITOR])
    # Seeking into a large file lands mid-line: a partial fragment, then whole
    # lines. The fragment must be dropped without losing the events after it.
    path = tmp_path / "events.jsonl"
    path.write_bytes(b'_at": "2026", "type": "mode_changed"}\n' + path.read_bytes())
    sidecar = RoomSidecar(port=1, home=tmp_path)

    assert [event["id"] for event in sidecar.events()] == [3, 2]


def test_missing_event_log_is_not_an_error(tmp_path) -> None:
    assert RoomSidecar(port=1, home=tmp_path).events() == []
    assert RoomSidecar(port=1, home=tmp_path).latest_notable_event() is None


def test_the_backlog_present_at_startup_does_not_flash_on_the_island() -> None:
    runtime = RuntimeStore()
    runtime.observe_room_event(NOTABLE, now=0.0)

    # Whatever was already in the log happened before Marvi was running.
    assert runtime.assistant.room_event is None

    runtime.observe_room_event(VISITOR, now=1.0)
    assert runtime.assistant.room_event is not None
    assert runtime.assistant.room_event.id == 3


def test_a_new_event_surfaces_then_expires() -> None:
    runtime = RuntimeStore()
    runtime.observe_room_event(AMBIENT, now=0.0)  # baseline
    runtime.observe_room_event(NOTABLE, now=100.0)
    surfaced = runtime.assistant.room_event

    runtime.observe_room_event(NOTABLE, now=100.0 + ROOM_EVENT_TTL_SECONDS - 1)
    still_there = runtime.assistant.room_event

    runtime.observe_room_event(None, now=100.0 + ROOM_EVENT_TTL_SECONDS + 1)

    assert surfaced is not None
    assert surfaced.summary == "mode changed to sleep"
    assert still_there is not None
    assert runtime.assistant.room_event is None


def test_the_same_event_is_not_resurfaced_after_it_expires() -> None:
    runtime = RuntimeStore()
    runtime.observe_room_event(AMBIENT, now=-1.0)  # baseline
    runtime.observe_room_event(NOTABLE, now=0.0)
    runtime.observe_room_event(NOTABLE, now=ROOM_EVENT_TTL_SECONDS + 1)
    assert runtime.assistant.room_event is None

    runtime.observe_room_event(VISITOR, now=ROOM_EVENT_TTL_SECONDS + 2)
    assert runtime.assistant.room_event is not None
    assert runtime.assistant.room_event.id == 3


def test_a_room_event_never_hijacks_a_live_voice_turn() -> None:
    runtime = RuntimeStore()
    runtime.assistant = runtime.assistant.model_copy(
        update={"phase": "listening", "caption": "Listening", "level": 0.7}
    )
    runtime.observe_room_event(AMBIENT, now=-1.0)  # baseline
    runtime.observe_room_event(NOTABLE, now=0.0)

    assert runtime.assistant.phase == "listening"
    assert runtime.assistant.caption == "Listening"
    assert runtime.assistant.level == 0.7
    assert runtime.assistant.room_event is not None


def test_a_room_event_never_clears_a_pending_confirmation() -> None:
    runtime = RuntimeStore()
    request = runtime.issue_confirmation(
        tool="room_set_light", arguments={"on": True}, action="Change light", detail="on=True"
    )
    runtime.observe_room_event(AMBIENT, now=-1.0)  # baseline
    runtime.observe_room_event(NOTABLE, now=0.0)

    assert runtime.assistant.confirmation is not None
    assert runtime.assistant.confirmation.token == request.token
    assert runtime.assistant.phase == "confirmation"


def test_a_malformed_event_is_ignored() -> None:
    runtime = RuntimeStore()
    runtime.observe_room_event({"no_id": True, "summary": "junk"}, now=0.0)
    assert runtime.assistant.room_event is None


@pytest.mark.asyncio
async def test_room_events_endpoint_serves_the_notable_tail(tmp_path) -> None:
    write_events(tmp_path, [AMBIENT, NOTABLE, VISITOR])
    app = create_app(
        version="0.1.0-test",
        runtime=RuntimeStore(audit_path=tmp_path / "audit.jsonl"),
        tools=ToolRegistry(),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://marvi.local"
    ) as client:
        response = await client.get("/room/events")

    # An explicitly supplied registry means no sidecar is wired; the endpoint
    # must answer empty rather than fail.
    assert response.status_code == 200
    assert response.json()["events"] == []
