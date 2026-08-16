"""Smart Room sidecar adapter.

The room engine at ``D:\\smart-room-plugin`` owns every device, automation, and
piece of room history. Marvi OS is a client: it speaks the sidecar's existing
authenticated JSON-RPC over loopback and never holds device credentials or
drives Tuya/MQTT itself.

Wire format (verified against the running runtime): one newline-terminated JSON
object per request carrying ``jsonrpc``, ``id``, ``method``, ``params`` and an
``auth`` token, answered by one newline-terminated JSON object.
"""

from __future__ import annotations

import json
import os
import socket
import time
import uuid
from pathlib import Path
from typing import Any

DEFAULT_PORT = 17842
DEFAULT_TIMEOUT = 8.0  # matches the sidecar's own bounded scene fades and retries
PROBE_TIMEOUT = 0.5  # status polling must never stall the health endpoint
PROBE_CACHE_SECONDS = 5.0

# Verified against the running runtime: set_light takes on/brightness/color_temp/rgb.
# "scene" is a label the sidecar derives, not an input.
COLOR_TEMP_RANGE = (2700, 6500)
ROOM_MODES = {"normal", "reading", "focus", "relax", "night", "sleep", "alarm", "off"}

EVENT_TAIL_BYTES = 64 * 1024

# The sidecar's event log is dominated by ambient vision state churn — in a
# 500-event sample, 446 were `vision_identity_state`. An always-on surface must
# allowlist rather than denylist: an unrecognised new type is better missed than
# blasted at the user every second. Add types here deliberately.
NOTABLE_EVENTS = frozenset(
    {
        "mode_changed",
        "light_changed",
        "presence_detected",
        "presence_cleared",
        "he20_occupied",
        "he20_cleared",
        "room_presence_unverified",
        "alarm_started",
        "alarm_acknowledged",
        "alarm_cancelled",
    }
)
# Deliberately excluded: `vision_gesture` fires in bursts (three inside fifteen
# seconds in the sampled log), and a gesture that actually does something
# already surfaces as the `light_changed` / `mode_changed` it caused.


def summarize_event(event: dict[str, Any]) -> str:
    """Build a line worth showing.

    The sidecar's own `summary` is a type label — `mode_changed` reports
    "mode changed" without the mode — so the detail is rebuilt from the payload
    and `summary` is only the fallback.
    """
    kind = event.get("type")
    source = event.get("source") or event.get("reason")
    suffix = f" ({source})" if source else ""

    if kind == "mode_changed":
        return f"Mode changed to {event.get('mode', 'unknown')}{suffix}"
    if kind == "light_changed":
        if not event.get("on"):
            return f"Light off{suffix}"
        parts = [f"{event['brightness']}%"] if event.get("brightness") is not None else []
        if event.get("color_temp"):
            parts.append(f"{event['color_temp']}K")
        detail = " ".join(parts)
        return f"Light on{' at ' + detail if detail else ''}{suffix}"
    if kind == "presence_cleared":
        return f"Presence cleared{suffix}"
    if kind == "presence_detected":
        return f"Presence detected{suffix}"
    if kind == "he20_occupied":
        return "Room occupancy confirmed"
    if kind == "he20_cleared":
        return "Room reported clear"
    if kind == "room_presence_unverified":
        return f"Unverified entry: {event.get('identity_reason', 'unknown reason')}"

    fallback = str(event.get("summary") or kind or "room event")
    return fallback[:1].upper() + fallback[1:]


class RoomUnavailableError(Exception):
    """The sidecar is not reachable. Conversation continues without it."""


class RoomRejectedError(Exception):
    """The sidecar reached a decision and refused the request."""


def _sidecar_home() -> Path:
    configured = os.environ.get("MARVI_ROOM_HOME")
    if configured:
        return Path(configured)
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(root) / "Hermes" / "smart_room"


class RoomSidecar:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int | None = None,
        home: Path | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.host = host
        self.port = port or int(os.environ.get("MARVI_ROOM_RPC_PORT", DEFAULT_PORT))
        self.home = home or _sidecar_home()
        self.timeout = timeout
        self._probe: tuple[float, bool] | None = None

    # -- transport ----------------------------------------------------------

    def _token(self) -> str:
        try:
            token = (self.home / ".rpc-token").read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RoomUnavailableError("room sidecar authentication is not initialized") from exc
        if not token:
            raise RoomUnavailableError("room sidecar authentication is not initialized")
        return token

    def call(
        self, method: str, params: dict[str, Any] | None = None, timeout: float | None = None
    ) -> dict[str, Any]:
        deadline = timeout if timeout is not None else self.timeout
        request = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex[:12],
            "method": method,
            "params": params or {},
            "auth": self._token(),
        }
        try:
            with socket.create_connection((self.host, self.port), timeout=deadline) as sock:
                sock.settimeout(deadline)
                sock.sendall(json.dumps(request).encode("utf-8") + b"\n")
                buffer = b""
                while b"\n" not in buffer:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    buffer += chunk
        except OSError as exc:
            raise RoomUnavailableError(
                f"room sidecar is not reachable on {self.host}:{self.port}"
            ) from exc

        if not buffer:
            raise RoomUnavailableError("room sidecar closed the connection without a response")

        try:
            response = json.loads(buffer.decode("utf-8").strip())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RoomUnavailableError("room sidecar returned malformed JSON") from exc

        if "error" in response:
            raise RoomRejectedError(str(response["error"]))
        result = response.get("result")
        if not isinstance(result, dict):
            raise RoomUnavailableError("room sidecar returned no result object")
        if result.get("success") is False:
            raise RoomRejectedError(str(result.get("error", "room command failed")))
        return result

    # -- loss-aware reads ---------------------------------------------------

    def snapshot(self) -> dict[str, Any] | None:
        """Last state the sidecar wrote to disk. Stale but useful while it restarts."""
        try:
            return json.loads((self.home / "state.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def state(self) -> dict[str, Any]:
        try:
            result = self.call("get_state", {"location_limit": 5})
            return {"live": True, "state": result.get("state", {})}
        except RoomUnavailableError:
            stale = self.snapshot()
            if stale is None:
                raise
            return {"live": False, "stale": True, "state": stale}

    def events(self, limit: int = 50, notable_only: bool = True) -> list[dict[str, Any]]:
        """Newest-first tail of the sidecar's event log.

        The sidecar has no events RPC; it appends JSONL. Only the tail is read,
        so this stays cheap as the log grows.
        """
        path = self.home / "events.jsonl"
        try:
            with path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                handle.seek(max(0, handle.tell() - EVENT_TAIL_BYTES))
                chunk = handle.read()
        except OSError:
            return []

        events: list[dict[str, Any]] = []
        # A partial first line is expected when seeking into the middle of the file.
        for line in reversed(chunk.decode("utf-8", "ignore").splitlines()):
            if len(events) >= limit:
                break
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            if notable_only and event.get("type") not in NOTABLE_EVENTS:
                continue
            events.append({**event, "summary": summarize_event(event)})
        return events

    def latest_notable_event(self) -> dict[str, Any] | None:
        found = self.events(limit=1)
        return found[0] if found else None

    def reachable(self) -> bool:
        try:
            self.call("ping", timeout=PROBE_TIMEOUT)
            return True
        except (RoomUnavailableError, RoomRejectedError):
            return False

    def status(self) -> tuple[str, str]:
        """Cached component state for the runtime snapshot. Polled every 2s by the app."""
        now = time.monotonic()
        if self._probe is None or now - self._probe[0] >= PROBE_CACHE_SECONDS:
            self._probe = (now, self.reachable())
        if self._probe[1]:
            return "ready", f"sidecar connected on {self.host}:{self.port}"
        if self.snapshot() is not None:
            return "error", "sidecar unreachable, serving last known room state"
        return "offline", "sidecar not connected"


def register_room_tools(registry, sidecar: RoomSidecar) -> None:
    """Register the small room tool surface. Device authority stays in the sidecar."""
    from .tools import ToolSpec

    def room_state() -> dict[str, Any]:
        return sidecar.state()

    def room_health() -> dict[str, Any]:
        return sidecar.call("get_health")

    def room_set_mode(mode: str) -> dict[str, Any]:
        if mode not in ROOM_MODES:
            raise RoomRejectedError(f"invalid mode: {mode}")
        return sidecar.call("set_mode", {"mode": mode})

    def room_set_light(
        on: bool, brightness: int | None = None, color_temp: int | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"on": on}
        if brightness is not None:
            if not 1 <= brightness <= 100:
                raise RoomRejectedError("brightness must be between 1 and 100")
            params["brightness"] = brightness
        if color_temp is not None:
            low, high = COLOR_TEMP_RANGE
            if not low <= color_temp <= high:
                raise RoomRejectedError(f"color_temp must be between {low} and {high}")
            params["color_temp"] = color_temp
        return sidecar.call("set_light", params)

    registry.register(
        ToolSpec(
            name="room_state",
            description="Read the current room state",
            arguments={},
            sensitive=False,
            handler=room_state,
        )
    )
    registry.register(
        ToolSpec(
            name="room_health",
            description="Read room device health",
            arguments={},
            sensitive=False,
            handler=room_health,
        )
    )
    registry.register(
        ToolSpec(
            name="room_set_mode",
            description="Change the room mode",
            arguments={"mode": str},
            sensitive=True,
            handler=room_set_mode,
        )
    )
    registry.register(
        ToolSpec(
            name="room_set_light",
            description="Change the room light",
            arguments={"on": bool},
            optional={"brightness": int, "color_temp": int},
            sensitive=True,
            handler=room_set_light,
        )
    )
