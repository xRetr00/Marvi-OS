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
            assert page.locator(".titlebar-clock").inner_text()
            # Nothing clicked: a fresh profile starts with Windows location on.
            page.locator(".weather-now strong").wait_for(timeout=90_000)
            page.locator('.leaflet-tile-loaded').first.wait_for()
            state = page.evaluate("window.marvi.getLocation()")
            evidence["native"] = {"status": state["status"], "mode": state["settings"]["mode"],
                "label": (state.get("place") or {}).get("label"),
                "source": (state.get("place") or {}).get("source"),
                "accuracy_m": (state.get("place") or {}).get("accuracy_m")}
            assert state["settings"]["mode"] == "automatic" and state["status"] == "ready", state
            assert page.locator(".weather-days>div").count() == 3
            page.screenshot(path=str(output / "overview.png"))
            evidence["checks"].append("auto-start: Windows fix, reverse-geocoded label and weather with no clicks")
            page.locator(".map-card-heading").click()
            if state["place"].get("coarse"):
                page.locator(".location-tip").wait_for()
            page.get_by_label("Find a place", exact=True).fill("Düzce Üniversitesi")
            page.get_by_role("button", name="Search", exact=True).click()
            page.locator(".location-results button").first.wait_for()
            page.locator(".location-results button").first.click()
            page.locator(".map-pin.is-draft").wait_for()
            page.locator(".pin-editor").get_by_role("button", name="Home", exact=True).click()
            page.get_by_role("button", name="Save pin", exact=True).click()
            page.locator(".location-pins li").first.wait_for()
            page.locator(".leaflet-marker-pane .map-pin").first.wait_for()
            state = page.evaluate("window.marvi.getLocation()")
            assert state["settings"]["saved"]["label"] == "Home", state["settings"]
            evidence["pinned"] = {"label": state["place"]["label"], "source": state["place"]["source"]}
            if state["place"].get("pinned"):
                page.get_by_text("Pin, matched by", exact=False).first.wait_for()
                # The pin's tip sits on the position dot, not somewhere near it.
                pin = page.locator(".leaflet-marker-pane .map-pin").first.bounding_box()
                dot = page.locator(".leaflet-overlay-pane path").last.bounding_box()
                tip = (pin["x"] + pin["width"] / 2, pin["y"] + pin["height"] * 1.2)
                centre = (dot["x"] + dot["width"] / 2, dot["y"] + dot["height"] / 2)
                assert abs(tip[0] - centre[0]) < 3 and abs(tip[1] - centre[1]) < 4, (tip, centre)
            page.screenshot(path=str(output / "pinned-home.png"))
            evidence["checks"].append("Photon place search; draft pin; saved as Home; fix snaps to the pin nearby")
            box = page.locator(".location-map").bounding_box()
            page.locator(".location-map").click(position={"x": box["width"] * 0.3, "y": box["height"] * 0.4})
            page.locator(".pin-editor").wait_for()
            # A locator, not wait_for_function: the app's CSP forbids eval.
            page.locator(".pin-editor small").filter(has_not_text="Looking up").wait_for(timeout=20_000)
            evidence["dropped_pin_address"] = page.locator(".pin-editor small").inner_text()
            page.screenshot(path=str(output / "dropped-pin.png"))
            page.locator(".pin-editor").get_by_role("button", name="Cancel", exact=True).click()
            evidence["checks"].append("click-to-pin with reverse-geocoded address")
            # Actual tool endpoint, using the per-launch token that Electron
            # wrote into this temporary profile. Never printed or persisted.
            token = (home / "state/local-token").read_text().strip()
            with httpx.Client(base_url=base, headers={"x-marvi-local": token}, timeout=20) as client:
                for tool in ("get_location", "get_local_time", "get_weather"):
                    result = client.post(f"/tools/{tool}", json={"arguments": {}})
                    assert result.status_code == 200 and result.json()["status"] == "executed"
            evidence["checks"].append("all three tools through real authenticated Gateway HTTP")
            page.get_by_role("button", name="Turn off", exact=True).click()
            page.get_by_text("No location selected", exact=True).wait_for()
            page.locator(".map-card-heading").click()  # Collapsed: no map without a place.
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
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        process.wait(timeout=15)
        server.should_exit = True
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
