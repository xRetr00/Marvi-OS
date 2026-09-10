"""Real Cua worker -> Windows fixture -> verified file boundary qualification."""

import json
import os
import re
import tempfile
import time
from pathlib import Path

from marvi_gateway.computer import ComputerUse
import marvi_gateway.computer as computer

os.environ["MARVI_COMPUTER_USE"] = "true"
root = Path(tempfile.mkdtemp(prefix="marvi-computer-proof-"))
service = ComputerUse()
pid = None
timings = {}


def act(name, arguments):
    started = time.perf_counter()
    result = service.action(name, arguments)
    timings.setdefault(name, []).append(
        round((time.perf_counter() - started) * 1000, 2)
    )
    assert not result["is_error"], (result.get("error_code"), result.get("observation"))
    return result


def targets(result):
    text = result["targets"]["text"]
    return json.loads(text[text.index("\n") + 1 : text.rindex("\n")])


def cursor_state(ended=False):
    async def read():
        result = await service._driver.call_tool("get_agent_cursor_state", json.dumps({"session": "Marvi"}))
        state = json.loads(result.structured_json or result.text)
        if ended:
            assert result.is_error and state["refusal"]["code"] == "session_ended"
        else:
            assert not result.is_error, "Cursor state unavailable"
        return state

    return service._runtime_loop().submit(read(), timeout=5)


try:
    launched = act(
        "launch_app",
        {
            "path": str(
                Path(os.environ["SystemRoot"])
                / "System32/WindowsPowerShell/v1.0/powershell.exe"
            ),
            "additional_arguments": [
                "-NoProfile",
                "-STA",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(Path(__file__).with_name("computer-fixture.ps1").resolve()),
                "-ResultPath",
                str(root / "result.txt"),
                *(["-VisualProof"] if os.environ.get("MARVI_CURSOR_VISUAL_PROOF") == "true" else []),
            ],
        },
    )
    pid = int(re.search(r"\(pid (\d+)\)", launched["observation"]["text"])[1])
    # A successful process launch need not have a window yet (cold WinForms).
    deadline = time.monotonic() + 20
    while True:
        windows = targets(act("list_windows", {"pid": pid}))["windows"]
        fixture = next((w for w in windows if w.get("title") == "Marvi Computer Qualification"), None)
        if fixture:
            window = fixture["window_id"]
            break
        assert time.monotonic() < deadline, "Fixture window did not become ready"
        time.sleep(0.25)
    state = targets(act("get_window_state", {"pid": pid, "window_id": window}))
    assert "MARVI_COMPUTER_PASSWORD_CANARY" not in json.dumps(state)
    text = next(e for e in state["elements"] if e.get("label") == "Fixture input")
    act(
        "set_value",
        {
            "pid": pid,
            "window_id": window,
            "element_token": text["element_token"],
            "value": "Marvi computer fixture",
        },
    )
    state = targets(act("get_window_state", {"pid": pid, "window_id": window}))
    button = next(e for e in state["elements"] if e.get("label") == "Save fixture")
    act(
        "click",
        {"pid": pid, "window_id": window, "element_token": button["element_token"]},
    )
    assert (root / "result.txt").read_text() == "Marvi computer fixture"
    if os.environ.get("MARVI_CURSOR_VISUAL_PROOF") == "true":
        act("bring_to_front", {"pid": pid})
    act("move_cursor", {"scope": "window", "x": fixture["bounds"]["x"] + 100, "y": fixture["bounds"]["y"] + 100})
    cursor = cursor_state()
    if os.environ.get("MARVI_CURSOR_VISUAL_PROOF") == "true":
        from PIL import ImageGrab
        time.sleep(0.35)
        bounds = fixture["bounds"]
        crop = (int(bounds["x"]), int(bounds["y"]), int(bounds["x"] + bounds["width"]), int(bounds["y"] + bounds["height"]))
        ImageGrab.grab(bbox=crop, include_layered_windows=True, all_screens=True).save(root / "cursor.png")
        print(json.dumps({"fixture_cursor_capture": str(root / "cursor.png")}))
    assert cursor["session"] == "Marvi" and cursor["enabled"]
    assert cursor["theme"]["id"] == "cua.default"
    print(json.dumps({"cursor_position": cursor.get("position"), "cursor_action": cursor.get("visual_state", {}).get("requested_action")}))
    service.control("stop")
    cursor_state(ended=True)
    service.control("resume")
    act("get_window_state", {"pid": pid, "window_id": window})
    assert cursor_state()["enabled"]
    service.control("private")
    cursor_state(ended=True)
    service.control("resume")
    # Force a real in-flight observation to time out. Recovery must retire its
    # worker before private input can be acknowledged or another worker starts.
    normal_timeout = computer.ACTION_TIMEOUT
    computer.ACTION_TIMEOUT = 0.001
    try:
        try:
            service.action("get_window_state", {"pid": pid, "window_id": window})
            raise AssertionError("Timeout was not exercised")
        except RuntimeError as exc:
            assert "outcome is unknown" in str(exc)
    finally:
        computer.ACTION_TIMEOUT = normal_timeout
    assert service.status()["state"] == "unknown", "Worker retirement did not finish"
    assert service._driver is None, "Timed-out worker was reused"
    service.control("private")
    assert service.status()["state"] == "private"
    try:
        service.action("get_window_state", {"pid": pid, "window_id": window})
        raise AssertionError("Private capture admitted")
    except RuntimeError:
        pass
    service.control("resume")
    act("kill_app", {"pid": pid})
    pid = None
    print(
        json.dumps(
            {
                "driver": "cua-driver 0.24.0",
                "native_app_launch": True,
                "fresh_element_tokens": True,
                "background_button": True,
                "file_result_verified": True,
                "private_resume": True,
                "password_canary_hidden": True,
                "native_timeout_worker_retired": True,
                "marvi_cursor_session": True,
                "cursor_hidden_on_stop_and_private": True,
                "app_close": True,
                "timings_ms": timings,
            }
        )
    )
finally:
    if pid:
        service.control("resume")
        service.action("kill_app", {"pid": pid})
    service.close()
