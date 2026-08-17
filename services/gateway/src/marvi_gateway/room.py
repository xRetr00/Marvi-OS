"""Smart Room sidecar adapter.

The room engine is a **desktop plugin** (`marvi_gateway.plugins`): Marvi clones
it from its repository, installs it, and starts it as a Gateway child process.
It owns every device, automation, and piece of room history. Marvi is a client:
it speaks the plugin's authenticated JSON-RPC over loopback and never holds
device credentials or drives Tuya/MQTT itself.

It used to read its state and RPC token out of `%LOCALAPPDATA%\\Hermes`, which
meant Marvi could only talk to a room that *another application* had started —
if that application was not installed or not running, the room simply did not
work and nothing said why. The plugin now lives under Marvi's own plugin data
root.

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

from .retry import Policy, RetriesExhaustedError, retry

DEFAULT_PORT = 17842
#: The plugin's own directory name inside the plugin data root. It is the
#: plugin's `name` in `plugin.yaml`, which is also its import name.
PLUGIN_NAME = "smart_room"
DEFAULT_TIMEOUT = 8.0  # matches the sidecar's own bounded scene fades and retries
PROBE_TIMEOUT = 0.5  # status polling must never stall the health endpoint
PROBE_CACHE_SECONDS = 5.0
# Short and few: a voice turn is waiting on this, so riding out a sidecar
# restart is worth a second or two and no more.
# `optional`: the sidecar is a separate program the user may simply not run.
ROOM_RECONNECT = Policy(
    attempts=3, base_seconds=0.2, max_seconds=1.0, budget_seconds=3.0, optional=True
)

# Verified against the running runtime: set_light takes on/brightness/color_temp/rgb.
# "scene" is a label the sidecar derives, not an input.
COLOR_TEMP_RANGE = (2700, 6500)
ROOM_MODES = {"normal", "reading", "focus", "relax", "night", "sleep", "alarm", "off"}

EVENT_TAIL_BYTES = 64 * 1024

# The engine's log is dominated by ambient vision state churn — in a 500-event
# sample, 413 were `vision_identity_state`. An always-on surface must allowlist
# rather than denylist: an unrecognised new type is better missed than blasted at
# the user every second. Add types here deliberately.
#
# Triaged against the events this engine really writes, rather than guessed at.
# The first version of this list allowlisted ten types and noticed four of the
# thirteen in the log — a phone arriving home, a device dropping off the network
# and every gesture went unseen.
#
# Deliberately still excluded, and why:
#
#   vision_identity_state       ambient, and it is state, not news. It belongs in
#                               the context line, which reads `state.vision`.
#   vision_gesture              one gesture emits a burst: measured against a real
#                               log, 98 events with runs of up to 41 consecutive
#                               ids. A gesture is a genuine intentional act and
#                               worth surfacing, but it needs debouncing to a
#                               single transition first, and an allowlist entry
#                               is not that. Adding it here would put 41 entries
#                               in the journal for one wave.
#   smart_room_state_reconciled bookkeeping the engine does to itself.
#   visitor_history_corrected   same.
NOTABLE_EVENTS = frozenset(
    {
        "mode_changed",
        "light_changed",
        "presence_detected",
        "presence_cleared",
        # Someone came in. The engine writes this alongside presence_detected
        # for an identified entry, and it carries who.
        "room_entry",
        # A device dropping off the network is the room quietly losing a limb:
        # the bulb stops answering, the ESP32 stops reporting, and every later
        # symptom looks like something else.
        "device_offline",
        "device_online",
        # OwnTracks. Arriving and leaving is exactly the kind of thing an
        # always-on assistant should know without being told.
        "phone_location_changed",
        # Falling asleep and waking are what the sleep rule turns on, so Marvi
        # should hear about them rather than infer them from a poll.
        "vision_sleep_state",
        "he20_occupied",
        "he20_cleared",
        "room_presence_unverified",
        "alarm_started",
        "alarm_acknowledged",
        "alarm_cancelled",
    }
)
# `vision_gesture` is admitted only when it carries a command. A bare gesture
# fires in bursts and means nothing; a gesture bound to a command is a
# deliberate instruction from a person in the room. Marvi consumes the
# sidecar's gesture inference rather than running a second pipeline for it.
GESTURE_EVENT = "vision_gesture"


def is_notable(event: dict[str, Any]) -> bool:
    kind = event.get("type")
    if kind == GESTURE_EVENT:
        return bool(event.get("command"))
    return kind in NOTABLE_EVENTS


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
    if kind == GESTURE_EVENT:
        return f"Gesture {event.get('gesture', 'unknown')} requested {event.get('command')}"

    fallback = str(event.get("summary") or kind or "room event")
    return fallback[:1].upper() + fallback[1:]


class RoomUnavailableError(Exception):
    """The sidecar is not reachable. Conversation continues without it."""


class RoomRejectedError(Exception):
    """The sidecar reached a decision and refused the request."""


class SleepProtectedError(Exception):
    """Refused because the room is in sleep mode.

    While someone is asleep the room is theirs, not Marvi's. The single
    exception is turning a light off: that is the one action whose worst case
    is a dark room someone was already sleeping in, and whose best case is
    fixing a light nobody wants on.
    """


def assert_sleep_safe(mode: str | None, light_on: bool, action: str, params: dict[str, Any]) -> None:
    """Enforce the sleep rule.

    Deliberately a pure function of the room's state and the requested action,
    so the rule can be read and tested without a sidecar.
    """
    if (mode or "").lower() != "sleep":
        return
    turning_light_off = action == "set_light" and params.get("on") is False
    if turning_light_off and light_on:
        return
    if turning_light_off and not light_on:
        raise SleepProtectedError("The room is asleep and the light is already off.")
    raise SleepProtectedError(
        f"The room is in sleep mode; {action} is not allowed. "
        "Only switching a light off is permitted while asleep."
    )


def read_sleep_state(sidecar: RoomSidecar) -> tuple[str | None, bool]:
    """The room's mode and light, for the sleep rule. Refuses rather than guesses.

    `RoomSidecar.state()` already falls back to the on-disk snapshot, so it
    raises only when there is *no* state at all — neither live nor stale. The
    first version of this treated that as "not asleep", which meant a room whose
    engine was not running would accept every write the rule exists to refuse.

    Not knowing is not the same as awake. This fails closed.
    """
    try:
        state = sidecar.state().get("state") or {}
    except RoomUnavailableError as exc:
        raise SleepProtectedError(
            "Marvi cannot tell whether the room is asleep, so it will not change it. "
            "Start the room plugin and try again."
        ) from exc
    return (
        ((state.get("modes") or {}).get("active_mode")),
        bool((state.get("light") or {}).get("on")),
    )


def _sidecar_home() -> Path:
    """Where the room plugin keeps its state and its RPC token.

    Under Marvi's plugin data root: the plugin is Marvi's to install and start,
    so its data belongs somewhere an uninstall can find and a backup can cover.
    `MARVI_ROOM_HOME` still overrides it, which is how someone already running
    the engine under another host points Marvi at that copy instead.
    """
    configured = os.environ.get("MARVI_ROOM_HOME")
    if configured:
        return Path(configured)
    from .plugins import data_root

    return data_root() / PLUGIN_NAME


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
        """Call the sidecar, riding out a restart.

        A fresh connection per call means there is no session to re-establish —
        the only failure worth retrying is a refusal while the sidecar is coming
        back up, which lasts seconds. A `RoomRejectedError` is the sidecar
        answering, and it will answer the same way next time.
        """
        try:
            return retry(
                lambda: self._call_once(method, params, timeout),
                what=f"room.{method}",
                policy=ROOM_RECONNECT,
                give_up_on=(RoomRejectedError,),
            )
        except RetriesExhaustedError as exhausted:
            # Retrying is an implementation detail. Every caller here catches
            # RoomUnavailableError, and changing the exception type under them
            # would turn a handled failure into an unhandled one.
            raise exhausted.cause from None

    def _call_once(
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
            if notable_only and not is_notable(event):
                continue
            events.append({**event, "summary": summarize_event(event)})
        return events

    def latest_notable_event(self) -> dict[str, Any] | None:
        found = self.events(limit=1)
        return found[0] if found else None

    def events_since(self, after_id: int | None, limit: int = 50) -> list[dict[str, Any]]:
        """Notable events newer than `after_id`, oldest first.

        `latest_notable_event` returns one event per call, and the Gateway called
        it once per health poll — so two notable things happening between polls
        meant one of them was never seen by anything. Presence clearing and a
        light going off within the same two seconds is not an unusual pair.

        Oldest first because these go into the journal, and the journal is a
        record of what happened in the order it happened.
        """
        found = self.events(limit=limit)
        if after_id is not None:
            found = [event for event in found if int(event.get("id", 0)) > after_id]
        return list(reversed(found))

    def reachable(self) -> bool:
        try:
            # Deliberately not retried: this asks whether the sidecar is up
            # right now. Retrying would both slow the health poll and answer a
            # different question than the one asked.
            self._call_once("ping", timeout=PROBE_TIMEOUT)
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
        current, light_on = read_sleep_state(sidecar)
        assert_sleep_safe(current, light_on, "set_mode", {"mode": mode})
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
        current, light_on = read_sleep_state(sidecar)
        assert_sleep_safe(current, light_on, "set_light", params)
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


#: The room plugin's tools that only read. Everything else is confirmed.
#:
#: Marvi decides this, not the plugin: a plugin declaring its own writes
#: harmless is exactly the claim that should not be taken at face value.
READ_ONLY_PLUGIN_TOOLS = frozenset(
    {"smart_room_state", "smart_room_health", "smart_room_diagnostic"}
)

#: Plugin tools that change the room, mapped to the action name the sleep rule
#: knows. A tool absent from here is still confirmed; it is simply not something
#: the sleep rule has an opinion about.
_SLEEP_GUARDED = {
    "smart_room_set_light": "set_light",
    "smart_room_set_mode": "set_mode",
    "smart_room_override": "override",
    "smart_room_alarm": "alarm",
}


def sleep_guard(sidecar: RoomSidecar):
    """A guard for `plugins.bridge_tools` that enforces the sleep rule.

    The plugin's own handlers know nothing about this rule — they enforce
    whatever their author decided. Bridging them without this would create a
    second path to the light that skips the guard the built-in tools apply,
    which is the one thing the sleep rule exists to prevent.

    Marvi supplies this; a plugin cannot register, replace or bypass it.
    """

    def guard(tool: str, arguments: dict[str, Any]) -> None:
        action = _SLEEP_GUARDED.get(tool)
        if action is None:
            return
        mode, light_on = read_sleep_state(sidecar)
        assert_sleep_safe(mode, light_on, action, arguments)

    return guard
