"""Computer-use admission, privacy, API and setup contracts."""

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from marvi_gateway.browser_privacy import capture_barrier
from marvi_gateway.computer import ComputerUse, computer_router, register_computer_tools
from marvi_gateway.runtime import RuntimeStore
from marvi_gateway.setup import catalog, tui
from marvi_gateway.tools import ToolRegistry


class Driver:
    def __init__(self):
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.wait = False
        self.closed = False

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name not in {"start_session", "set_agent_cursor_enabled"}:
            self.entered.set()
        if self.wait and name not in {"start_session", "set_agent_cursor_enabled"}:
            await asyncio.to_thread(self.release.wait)
        return SimpleNamespace(
            text="fixture result", images=[], is_error=False, error_code=None, degraded=False
        )

    async def list_tools_json(self):
        return json.dumps(
            {
                "tools": [
                    {"name": name, "inputSchema": {"properties": {}}}
                    for name in ["click", "get_browser_state", "set_config"]
                ]
            }
        )

    async def shutdown(self):
        self.closed = True


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setenv("MARVI_COMPUTER_USE", "true")
    driver = Driver()
    s = ComputerUse(factory=lambda: driver)
    yield s, driver
    driver.release.set()
    s.close()
    capture_barrier.leave("computer-use")


def test_catalog_keeps_browser_and_driver_configuration_out(service):
    s, _ = service
    assert [t["name"] for t in s.catalog()["actions"]] == ["click"]
    with pytest.raises(ValueError):
        s.action("set_config", {})


def test_cursor_is_named_marvi_and_hidden_before_private_input(service):
    s, d = service
    s.action("click", {})
    calls = [(name, json.loads(args)) for name, args in d.calls]
    assert calls == [
        ("start_session", {"session": "Marvi", "cursor_theme": {"theme_id": "cua.default", "reduced_motion": "auto"}}),
        ("set_agent_cursor_enabled", {"session": "Marvi", "enabled": True}),
        ("click", {"session": "Marvi"}),
        ("set_agent_cursor_enabled", {"session": "Marvi", "enabled": False}),
    ]
    s.control("private")
    assert not json.loads(d.calls[-1][1])["enabled"]
    s.control("resume")
    s.action("list_apps", {})
    assert d.calls[-1] == ("list_apps", "{}")
    with pytest.raises(ValueError, match="omit session"):
        s.action("click", {"session": "someone else"})


def test_failed_action_still_hides_cursor(service):
    s, d = service
    original = d.call_tool

    async def fail(name, args):
        if name == "click":
            raise RuntimeError("fixture input error")
        return await original(name, args)

    d.call_tool = fail
    with pytest.raises(RuntimeError):
        s.action("click", {})
    assert json.loads(d.calls[-1][1]) == {"session": "Marvi", "enabled": False}


def test_stop_does_not_claim_issued_action_was_cancelled(service):
    s, d = service
    d.wait = True
    worker = threading.Thread(target=lambda: s.action("click", {}))
    worker.start()
    assert d.entered.wait(2)
    assert s.control("stop")["state"] == "stopping"
    assert s.status()["active"]
    with pytest.raises(RuntimeError):
        s.action("click", {})
    d.release.set()
    worker.join(3)
    assert s.status()["state"] == "paused"
    s.control("resume")
    assert not s.action("list_apps", {})["is_error"]


def test_private_waits_for_capture_and_blocks_new_actions(service):
    s, d = service
    d.wait = True
    action = threading.Thread(target=lambda: s.action("click", {}))
    action.start()
    assert d.entered.wait(2)
    done = threading.Event()
    private = threading.Thread(target=lambda: (s.control("private"), done.set()))
    private.start()
    assert not done.wait(0.1)
    d.release.set()
    action.join(3)
    private.join(3)
    assert done.is_set() and capture_barrier.blocked
    with pytest.raises(RuntimeError):
        s.action("get_desktop_state", {})
    s.control("resume")
    assert not capture_barrier.blocked


def test_confirmation_and_audit_do_not_expose_typed_text(service, tmp_path):
    s, _ = service
    r = ToolRegistry()
    register_computer_tools(r, s)
    spec = r.get("computer_action")
    args = {
        "action": "type_text",
        "arguments": {"text": "SECRET_CANARY"},
        "request_confirmation": True,
    }
    assert spec.is_sensitive(args)
    assert not spec.is_sensitive({**args, "request_confirmation": False})
    assert "SECRET_CANARY" not in spec.summary(args)
    runtime = RuntimeStore(audit_path=tmp_path / "audit.jsonl")
    runtime.audit("requested", "computer_action", args, "SECRET_CANARY")
    assert "SECRET_CANARY" not in (tmp_path / "audit.jsonl").read_text()


@pytest.mark.asyncio
async def test_control_api_requires_auth_and_valid_command(service, monkeypatch):
    monkeypatch.setenv("MARVI_LOCAL_TOKEN", "computer-fixture")
    s, _ = service
    app = FastAPI()
    app.include_router(computer_router(s))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as c:
        assert (await c.get("/computer")).status_code == 403
        c.headers["x-marvi-local"] = "computer-fixture"
        assert (await c.get("/computer?after=-1")).status_code == 422
        initial = (await c.get("/computer")).json()
        assert (await c.post("/computer/control", json={"command": "stop"})).status_code == 200
        changed = (await c.get(f"/computer?after={initial['revision']}")).json()
        assert changed["state"] == "paused" and changed["revision"] > initial["revision"]
        assert (await c.post("/computer/control", json={"command": "invalid"})).status_code == 422


def test_setup_has_pinned_install_and_opt_in():
    root = Path(__file__).resolve().parents[3]
    component = catalog.get(root, "computer-use")
    assert component and component.extra["version"] == "0.24.0"
    assert all(f.size and len(f.sha256) == 64 for f in component.files)
    capability = next(c for c in tui.CAPABILITIES if c.key == "computer-use")
    assert capability.settings[0].name == "MARVI_COMPUTER_USE"


def test_idle_status_watch_wakes_for_action_and_completion(service):
    s, d = service
    d.wait = True
    previous = s.status()["revision"]
    worker = threading.Thread(target=lambda: s.action("click", {}))
    worker.start()
    assert d.entered.wait(2)
    running = s.watch(previous, timeout=0.1)
    assert running["active"] and running["revision"] > previous
    d.release.set()
    worker.join(2)
    finished = s.watch(running["revision"], timeout=0.1)
    assert not finished["active"] and finished["revision"] > running["revision"]


def test_a_hung_driver_releases_the_lease_instead_of_bricking_both_subsystems(service, monkeypatch):
    """One unanswered native call used to disable computer use until restart.

    `submit(..., timeout=None)` is `future.result(None)`, so a driver that
    never answers held the request thread, `_active`, and a `capture_barrier`
    observer for ever. After that every action raised "busy or paused",
    `resume` raised "Wait for the current action to finish", and -- because the
    barrier is shared -- the browser's private input could not start either.
    """
    import marvi_gateway.computer as computer

    s, d = service
    monkeypatch.setattr(computer, "ACTION_TIMEOUT", 0.2)
    d.wait = True

    with pytest.raises(RuntimeError) as hung:
        s.action("click", {})
    # Careful about the claim: it was issued and may well have landed.
    assert "unknown" in str(hung.value).lower()
    assert "cancel" not in str(hung.value).lower()

    # The lease is back, the barrier is clear, and the advice it gave -- go and
    # look at the screen -- is something it will actually let you do.
    assert s.status()["state"] == "unknown"
    assert not s.status()["active"]
    assert not capture_barrier.blocked
    d.release.set()
    d.wait = False
    assert s.action("get_desktop_state", {})["is_error"] is False


def test_private_input_elsewhere_is_a_refusal_not_a_maybe(service):
    """Saying "completion may be unknown" about a thing never attempted.

    `observe()` raises when the barrier is held by anyone -- including a
    browser session, since they share it -- and nothing is dispatched. That
    went through the same blanket handler as a real failure, so the model was
    told the action might have landed and could reasonably go and undo it, or
    do it twice.
    """
    s, d = service
    capture_barrier.enter("some-browser-session")
    try:
        with pytest.raises(RuntimeError) as refused:
            s.action("click", {})
        assert "Nothing was done" in str(refused.value)
        assert "unknown" not in str(refused.value).lower()
        assert d.calls == []
    finally:
        capture_barrier.leave("some-browser-session")

    # And the refusal did not consume the lease.
    assert not s.status()["active"]
    assert s.action("click", {})["is_error"] is False


def test_timeout_keeps_capture_lease_until_native_shutdown_acknowledges(service, monkeypatch):
    import marvi_gateway.computer as computer

    s, d = service
    monkeypatch.setattr(computer, "ACTION_TIMEOUT", 0.05)
    monkeypatch.setattr(computer, "RECOVERY_TIMEOUT", 0.05)
    d.wait = True
    shutdown_entered = threading.Event()
    shutdown_done = threading.Event()

    async def shutdown():
        shutdown_entered.set()
        await asyncio.to_thread(d.release.wait)
        shutdown_done.set()

    d.shutdown = shutdown
    with pytest.raises(RuntimeError, match="unknown"):
        s.action("click", {})
    assert shutdown_entered.wait(1)
    assert s.status()["state"] == "stopping"
    with pytest.raises(TimeoutError):
        capture_barrier.enter("browser-retirement-test", timeout=0.05)
    capture_barrier.leave("browser-retirement-test")
    with pytest.raises(RuntimeError):
        s.control("resume")
    d.release.set()
    assert shutdown_done.wait(2)
    s._runtime_loop().submit(asyncio.sleep(0))
    assert s.status()["state"] == "unknown"
    assert s._driver is None
    capture_barrier.enter("browser-retirement-test", timeout=0.1)
    capture_barrier.leave("browser-retirement-test")


def test_failed_retirement_cannot_resume_or_acknowledge_private_input(service, monkeypatch):
    import marvi_gateway.computer as computer

    s, d = service
    monkeypatch.setattr(computer, "ACTION_TIMEOUT", 0.05)
    d.wait = True
    original_shutdown = d.shutdown

    async def failed_shutdown():
        raise RuntimeError("fixture shutdown failure")

    d.shutdown = failed_shutdown
    try:
        with pytest.raises(RuntimeError, match="unknown"):
            s.action("click", {})
        assert s.status()["state"] == "unavailable"
        for command in ("resume", "private", "stop"):
            with pytest.raises(RuntimeError, match="Restart Marvi"):
                s.control(command)
        with pytest.raises(RuntimeError):
            s.action("get_desktop_state", {})
        with pytest.raises(TimeoutError):
            capture_barrier.enter("browser-failed-retirement", timeout=0.01)
    finally:
        capture_barrier.leave("browser-failed-retirement")
        d.shutdown = original_shutdown


def test_private_input_that_cannot_start_does_not_leave_the_door_shut(service, monkeypatch):
    """`block` runs before the wait, so a failed `enter` used to close everything.

    `enter` closes admission first and then waits for readers. With no timeout
    that wait was forever; with one, returning without releasing would leave
    `_private` populated and every browser and computer action refused, with no
    command able to clear it.
    """
    import marvi_gateway.computer as computer

    s, d = service
    monkeypatch.setattr(computer, "PRIVATE_TIMEOUT", 0.2)
    d.wait = True
    threading.Thread(target=lambda: s.action("click", {}), daemon=True).start()
    assert d.entered.wait(2)

    with pytest.raises(RuntimeError, match="private input did not start"):
        s.control("private")
    assert not capture_barrier.blocked

    d.release.set()
