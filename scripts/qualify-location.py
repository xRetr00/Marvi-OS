"""Real packaged Electron -> IPC -> Gateway HTTP -> Windows/Open-Meteo proof.

Run after npm run build:unpack: uv run --project services/gateway python
scripts/qualify-location.py. Uses a temporary profile; never changes the user's
running installation. Live APIs and Windows permission are required.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from playwright.sync_api import sync_playwright


def unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    output = repo / "output" / "playwright" / "location"
    output.mkdir(parents=True, exist_ok=True)
    home = Path(tempfile.mkdtemp(prefix="marvi-location-proof-"))
    os.environ["MARVI_HOME"] = str(home)
    os.environ["MARVI_LOG_DIR"] = str(home / "logs")
    os.environ["MARVI_ANNOUNCE"] = "0"
    os.environ["MARVI_EMBEDDING_SOURCE"] = "off"
    os.environ.pop("MARVI_LOCAL_TOKEN", None)
    (home / "providers.env").write_text("MARVI_WAKE_AUTO_RESTART=0\n", encoding="utf-8")
    (home / "pet.json").write_text('{"enabled":false}', encoding="utf-8")

    from marvi_gateway.app import create_app
    from marvi_gateway.location import register_location_tools
    from marvi_gateway.tools import ToolRegistry

    registry = ToolRegistry()
    application = create_app(tools=registry)
    register_location_tools(registry, application.state.location)
    gateway_port, debug_port = unused_port(), unused_port()
    base = f"http://127.0.0.1:{gateway_port}"
    # The real app/router runs over a real socket. Lifespan is disabled because
    # voice/media/model warming is outside this feature's qualification.
    server = uvicorn.Server(uvicorn.Config(application, host="127.0.0.1", port=gateway_port,
                                           lifespan="off", log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    executable = repo / "apps/desktop/dist/win-unpacked/Marvi-OS.exe"
    assert executable.exists(), "Build the Windows app first"
    env = {**os.environ, "MARVI_MANAGE_VOICE_STACK": "0", "MARVI_GATEWAY_URL": base}
    started = time.monotonic()
    process = subprocess.Popen([str(executable), f"--user-data-dir={home / 'profile'}",
                                f"--remote-debugging-port={debug_port}"], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    evidence = {"windows": os.sys.getwindowsversion().build, "native": {}, "checks": []}
    try:
        with httpx.Client(timeout=1) as client:
            for _ in range(100):
                try:
                    if client.get(f"http://127.0.0.1:{debug_port}/json/version").is_success:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.2)
            else:
                raise AssertionError("Packaged app debugging endpoint did not start")
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{debug_port}")
            page = next(p for context in browser.contexts for p in context.pages if "surface=main" in p.url)
            page.set_default_timeout(30_000)
            page.bring_to_front()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.get_by_role("button", name="Set location", exact=True).wait_for()
            assert page.locator(".titlebar-clock").inner_text()
            evidence["checks"].append("real preload and Overview empty state; titlebar clock")
            page.get_by_role("button", name="Set location", exact=True).click()
            page.get_by_label("Save a city", exact=True).fill("Istanbul")
            page.get_by_role("button", name="Search", exact=True).click()
            page.locator(".location-results button").first.wait_for()
            page.locator(".location-results button").first.click()
            page.locator(".weather-now strong").wait_for()
            page.locator('.leaflet-tile-loaded').first.wait_for()
            assert page.locator(".leaflet-overlay-pane path").count() >= 1
            page.locator(".map-card-heading").click()
            page.screenshot(path=str(output / "overview.png"))
            evidence["checks"].append("live geocoding; saved location; weather/three-day forecast; real OSM tiles and marker")
            assert page.locator(".weather-days>div").count() == 3
            page.locator(".map-card-heading").click()
            page.get_by_role("button", name="Use Windows location", exact=True).click()
            page.locator('.location-feedback[role=status]').wait_for(state='hidden', timeout=120_000)
            state = page.evaluate("window.marvi.getLocation()")
            evidence["native"] = {"status": state["status"],
                "source": (state.get("place") or {}).get("source"),
                "accuracy_m": (state.get("place") or {}).get("accuracy_m")}
            assert state["status"] == "ready", f"Native location needs qualification: {state['status']}"
            page.locator(".weather-now strong").wait_for()
            page.locator(".map-card-heading").click()
            page.screenshot(path=str(output / "native-location.png"))
            evidence["checks"].append("explicit Windows consent/read through packaged helper; weather for native fix")
            # Actual tool endpoint, using the per-launch token that Electron
            # wrote into this temporary profile. Never printed or persisted.
            token = (home / "state/local-token").read_text().strip()
            with httpx.Client(base_url=base, headers={"x-marvi-local": token}, timeout=20) as client:
                for tool in ("get_location", "get_local_time", "get_weather"):
                    result = client.post(f"/tools/{tool}", json={"arguments": {}})
                    assert result.status_code == 200 and result.json()["status"] == "executed"
            evidence["checks"].append("all three tools through real authenticated Gateway HTTP")
            page.locator(".map-card-heading").click()
            page.get_by_role("button", name="Turn off", exact=True).click()
            page.get_by_text("No location selected", exact=True).wait_for()
            assert page.locator(".leaflet-tile").count() == 0
            assert page.locator(".weather-now").count() == 0
            evidence["checks"].append("off removes coordinates, weather and map tiles")
            assert not errors, errors
            evidence["page_errors"] = errors
            evidence["elapsed_seconds"] = round(time.monotonic() - started, 2)
            (output / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            print(json.dumps(evidence, indent=2))
            browser.close()
    finally:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        process.wait(timeout=15)
        server.should_exit = True
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
