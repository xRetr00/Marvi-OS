"""Real Cua worker -> Windows fixture -> verified file boundary qualification."""

import json
import os
import re
import tempfile
import time
from pathlib import Path

from marvi_gateway.computer import ComputerUse

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
    assert not result["is_error"], result.get("error_code")
    return result


def targets(result):
    text = result["targets"]["text"]
    return json.loads(text[text.index("\n") + 1 : text.rindex("\n")])


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
            ],
        },
    )
    pid = int(re.search(r"\(pid (\d+)\)", launched["observation"]["text"])[1])
    window = int(re.search(r"window_id: (\d+)", launched["observation"]["text"])[1])
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
