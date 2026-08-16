"""The sleep rule.

While the room is asleep it belongs to the person in it. Marvi may do exactly
one thing: switch a light off. Everything else is refused, no matter who asks
— voice, the mind, vision, or YOLO.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from marvi_gateway.app import create_app
from marvi_gateway.room import (
    RoomSidecar,
    SleepProtectedError,
    assert_sleep_safe,
    register_room_tools,
)
from marvi_gateway.runtime import RuntimeStore
from marvi_gateway.tools import ToolRegistry

# -- the rule itself --------------------------------------------------------


@pytest.mark.parametrize("mode", ["normal", "focus", "relax", "reading", "night", None, ""])
def test_outside_sleep_everything_is_permitted(mode) -> None:
    assert_sleep_safe(mode, True, "set_light", {"on": True, "brightness": 100})
    assert_sleep_safe(mode, False, "set_mode", {"mode": "focus"})


def test_asleep_a_light_that_is_on_may_be_switched_off() -> None:
    # The one permitted action, and the reason the rule is not simply "never".
    # Returning without raising is the whole assertion.
    assert_sleep_safe("sleep", True, "set_light", {"on": False})


def test_asleep_turning_a_light_on_is_refused() -> None:
    with pytest.raises(SleepProtectedError, match="not allowed"):
        assert_sleep_safe("sleep", False, "set_light", {"on": True})


def test_asleep_brightening_a_light_is_refused() -> None:
    with pytest.raises(SleepProtectedError):
        assert_sleep_safe("sleep", True, "set_light", {"on": True, "brightness": 100})


def test_asleep_changing_the_mode_is_refused() -> None:
    with pytest.raises(SleepProtectedError, match="sleep mode"):
        assert_sleep_safe("sleep", True, "set_mode", {"mode": "normal"})


def test_asleep_with_the_light_already_off_there_is_nothing_to_do() -> None:
    with pytest.raises(SleepProtectedError, match="already off"):
        assert_sleep_safe("sleep", False, "set_light", {"on": False})


def test_the_rule_is_case_insensitive() -> None:
    with pytest.raises(SleepProtectedError):
        assert_sleep_safe("SLEEP", False, "set_light", {"on": True})


# -- enforced at the boundary, for every caller -----------------------------


class FakeSidecar(RoomSidecar):
    def __init__(self, mode="sleep", light_on=True, reachable=True):
        super().__init__(port=1, home=None)
        self._mode = mode
        self._light_on = light_on
        self._reachable = reachable
        self.calls: list[tuple[str, dict]] = []

    def state(self):
        if not self._reachable:
            from marvi_gateway.room import RoomUnavailableError

            raise RoomUnavailableError("down")
        return {
            "live": True,
            "state": {"modes": {"active_mode": self._mode}, "light": {"on": self._light_on}},
        }

    def snapshot(self):
        return {"modes": {"active_mode": self._mode}, "light": {"on": self._light_on}}

    def call(self, method, params=None, timeout=None):
        self.calls.append((method, params or {}))
        return {"success": True}

    def connections(self):  # unused here
        return []


def build(sidecar, tmp_path, yolo=False):
    registry = ToolRegistry()
    register_room_tools(registry, sidecar)
    runtime = RuntimeStore(audit_path=tmp_path / "audit.jsonl")
    runtime.set_yolo(yolo)
    app = create_app(version="0.1.0-test", runtime=runtime, tools=registry)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://m.local")


@pytest.mark.asyncio
async def test_yolo_does_not_override_the_sleep_rule(tmp_path) -> None:
    sidecar = FakeSidecar(mode="sleep", light_on=False)
    client = build(sidecar, tmp_path, yolo=True)
    async with client:
        response = await client.post(
            "/tools/room_set_light", json={"arguments": {"on": True, "brightness": 100}}
        )

    # YOLO removes the prompt, never the protection.
    assert response.json()["status"] == "failed"
    assert "sleep mode" in response.json()["error"]
    assert sidecar.calls == []


@pytest.mark.asyncio
async def test_switching_the_light_off_still_works_while_asleep(tmp_path) -> None:
    sidecar = FakeSidecar(mode="sleep", light_on=True)
    client = build(sidecar, tmp_path, yolo=True)
    async with client:
        response = await client.post("/tools/room_set_light", json={"arguments": {"on": False}})

    assert response.json()["status"] == "executed"
    assert sidecar.calls == [("set_light", {"on": False})]


@pytest.mark.asyncio
async def test_mode_changes_are_blocked_while_asleep(tmp_path) -> None:
    sidecar = FakeSidecar(mode="sleep")
    client = build(sidecar, tmp_path, yolo=True)
    async with client:
        response = await client.post(
            "/tools/room_set_mode", json={"arguments": {"mode": "normal"}}
        )

    assert response.json()["status"] == "failed"
    assert sidecar.calls == []


@pytest.mark.asyncio
async def test_normal_mode_is_unaffected(tmp_path) -> None:
    sidecar = FakeSidecar(mode="focus", light_on=False)
    client = build(sidecar, tmp_path, yolo=True)
    async with client:
        response = await client.post(
            "/tools/room_set_light", json={"arguments": {"on": True, "brightness": 60}}
        )

    assert response.json()["status"] == "executed"
    assert sidecar.calls[0][0] == "set_light"


@pytest.mark.asyncio
async def test_a_stale_snapshot_still_protects_sleep(tmp_path) -> None:
    """If live state is unavailable the guard falls back rather than opening up."""
    sidecar = FakeSidecar(mode="sleep", light_on=False, reachable=False)
    client = build(sidecar, tmp_path, yolo=True)
    async with client:
        response = await client.post("/tools/room_set_light", json={"arguments": {"on": True}})

    assert response.json()["status"] == "failed"
    assert "sleep" in response.json()["error"]
    assert sidecar.calls == []
