# Phase 4 — Tools, Confirmation, and Smart Room

**Status:** complete
**Depends on:** Phase 3

## Scope

- Narrow structured tool router and append-only audit events.
- LLM-requested Confirm mode and explicit global YOLO mode.
- Spoken and Island approval resolve the same exact-argument Gateway token.
- Connect `D:\smart-room-plugin` as an independent sidecar for actions, events,
  and logs; do not move device authority into Marvi OS.

## Acceptance evidence required

- Token replay/argument mutation rejection.
- Persistent visible YOLO indicator in the status bar/tray and zero
  confirmations while enabled; the idle Island remains recessed.
- Loss-aware room reconnect and ordinary conversation during sidecar failure.

## Implemented

- `marvi_gateway.tools`: a registry where every tool declares its exact argument
  names and types. Unknown tools, missing arguments, unexpected arguments, and
  wrong types are refused before any handler runs. `bool` is never accepted for
  an `int` parameter.
- Exact-argument confirmation tokens in `marvi_gateway.runtime`: 24-byte
  URL-safe tokens, single-use, 120-second TTL, bound to a canonical JSON
  fingerprint of the arguments they were issued for. A mismatch burns the token
  instead of executing a different action.
- Append-only JSONL audit of `requested`, `confirmation_required`, `approved`,
  `denied`, `executed`, `failed`, `expired`, and `argument_mismatch`, each
  stamped with the active mode. YOLO executions are audited exactly like
  confirmed ones.
- `marvi_gateway.room`: a thin client for the sidecar's authenticated
  newline-delimited JSON-RPC on `127.0.0.1:17842`. Reads fall back to the
  sidecar's on-disk snapshot while it is unreachable; the auth token is re-read
  per call so a sidecar restart that rotates it needs no Gateway restart.
- Room tool surface kept to four: `room_state`, `room_health` (reads, never
  gated) and `room_set_mode`, `room_set_light` (sensitive).
- `marvi_agent.tools`: five voice-sized function tools including
  `approve_pending_action` / `deny_pending_action`, so spoken approval resolves
  the same token and the same arguments the Island resolves. Verified against
  livekit-agents 1.6.10 — `RunContext` and the token never enter the
  LLM-visible schema.
- Room and Activity control-center pages read live sidecar state, room event
  history, and the real audit timeline instead of placeholder copy.
- Room events read from the sidecar's JSONL log by tail, with an explicit
  notable-event allowlist. In a 500-event sample, 446 were ambient
  `vision_identity_state`; an always-on surface allowlists so an unrecognised
  new type is missed rather than blasted at the user every second.
  `vision_gesture` is excluded because it fires in bursts and any gesture that
  does something already surfaces as the `light_changed` it caused.
- Event lines are rebuilt from the payload. The sidecar's own `summary` is a
  type label — `mode_changed` reports "mode changed" with no mode — so it is
  only the fallback.
- Island micro-events ride a dedicated `room_event` channel on the assistant
  state rather than the `phase`, so a background event cannot overwrite a live
  voice turn or a pending confirmation. It expands the seed for 25 seconds,
  never becomes interactive, and never pulls focus. The first observation after
  startup only establishes a baseline, so a stale backlog entry cannot flash on
  launch.

## Evidence

Recorded against a live smart-room runtime (ESP32, Tuya RGBCW bulb, and HE20
sensor all online) driven through a real `uvicorn` Gateway process over HTTP,
not an in-process transport.

| Gate | Result |
|---|---|
| Sensitive write asks first | `confirmation_required`; Island shows `Change the room light (brightness=30, on=True)` |
| Approval with exact arguments | `executed`; bulb physically moved 100% → 30%, device `dps` confirmed |
| Argument mutation (55 → 100) | HTTP 409, token burned, `argument_mismatch` audited |
| Replay with original arguments after a burn | HTTP 404 |
| Forged token | HTTP 404 |
| Unknown tool / extra argument | HTTP 404 / HTTP 422, handler never reached |
| YOLO | flag persists across polls; sensitive tools execute with no token and are still audited |
| Sidecar unreachable | room component `error`, reads served from the stale snapshot, writes fail cleanly, Gateway and assistant phase unaffected |
| Sidecar returns with a rotated token | room component back to `ready` and reads live again, with no Gateway restart |
| Room event filtering | 147 ambient `vision_identity_state` suppressed from a live tail; only real transitions served |
| Rebuilt event lines | `Light on at 100% 6500K (manual)`, `Mode changed to focus (manual)`, `Unverified entry: stale_owntracks` |
| Micro-event isolation | `phase` stayed `ready` and `caption` unchanged while `room_event` carried the event |
| Fresh start | no stale backlog entry surfaced on the Island; history endpoint still served it |

Automated coverage: 37 Gateway tests, 9 voice-tool tests driving the real
Gateway app, and 22 desktop tests.

## Method note

The loss-aware reconnect was proven by pointing the Gateway at a dead port and
bringing a real sidecar back on it with a rotated token — real sockets and real
processes, but not the production room runtime, which was deliberately left
running while in use.

## Follow-on work (not Phase 4)

- Composio and other non-room tools belong to Phase 5; the router intentionally
  carries only the room surface today.
- Room event history is not yet exposed as a voice tool. Add it when the agent
  is actually asked to reason over it.
