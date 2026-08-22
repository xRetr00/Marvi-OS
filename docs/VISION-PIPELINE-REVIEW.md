# Vision pipeline review

Status: reviewed against the Gateway and independent Smart Room repositories on
2026-08-23. This document describes the code that exists, not an aspirational
status screen.

## Current truth

Marvi currently has an **on-demand** local face pipeline in `vision.py`. It is
enabled only by `MARVI_VISION`, opens the Windows camera for a bounded request,
motion-gates InsightFace `buffalo_l` inference on CPU, matches owner/known face
embeddings, and stores unknown sightings plus cropped face thumbnails in
Marvi's local vision directory. `vision_describe` separately captures one frame
and can send it to the configured VLM endpoint. It is not an always-on presence,
gesture, activity, or sleep pipeline.

The independent Smart Room sidecar currently owns mmWave, BLE, OwnTracks,
lights, modes, alarms, and visitor entries inferred from room/phone evidence.
It has no camera capture, face database, gesture model, or `state.vision` schema.
Therefore `room_provides_vision()` currently returns false unless a future
sidecar explicitly writes `vision.enabled`.

Smart Room context enters both chat and voice through its registered context
provider. The Gateway calls `plugins.context_lines`, bounds each line to 240
characters, and appends it after the stable identity prompt so changing room
state does not invalidate the cacheable prefix. Today that line contains room
presence, location, mode, and light state; it contains no camera-derived facts.

Smart Room events are tailed from `events.jsonl`, allowlisted, summarized, and
written to the Gateway journal. The Mind evaluates those trusted events against
quiet hours, presence, cooldown, token budget, and per-event surface ceilings.
This is the correct route for welcomes, alarms, and visitor reports. Raw frames,
embeddings, coordinates, and verbose logs must never be injected into the
prompt.

## Problems to resolve

1. Camera ownership is only an implicit convention. A future sidecar vision
   flag could disable Gateway vision, but there is no lease, health timestamp,
   or capability contract proving that the sidecar is actually watching.
2. The Gateway's face library and the Smart Room's visitor-entry queue are two
   different identity systems. One uses face embeddings; the other uses BLE,
   OwnTracks, and mmWave evidence.
3. Vision health currently means the on-demand face library was constructed,
   not that a camera is open, frames are fresh, or inference is healthy.
4. The on-demand `vision_describe` path may transmit a frame to a cloud VLM.
   That boundary needs an explicit UI disclosure and policy decision.
5. Always-on camera logic has no recorded-fixture harness, reconnect soak, or
   privacy invariant yet.

## Target architecture

Smart Room should become the **single physical camera owner**, because it
already owns room presence and gestures. Marvi Gateway remains the policy,
tool, prompt, and cloud-egress boundary.

```text
Windows camera
  -> sidecar capture + freshness/lease
  -> cheap motion/person gate
  -> local face / gesture / posture analyzers
  -> bounded state.vision + structured events
  -> authenticated loopback RPC
  -> Gateway context, tools, Journal, Mind, Island/voice
```

The sidecar should expose versioned capabilities and freshness:

- `vision.enabled`, `vision.camera_id`, `vision.last_frame_at`, and health;
- bounded facts such as person count, owner-visible confidence, activity,
  gesture command, and sleep state;
- `vision_observe` for the latest structured observation;
- a one-shot snapshot RPC used only when `vision_describe` is explicitly
  requested and policy permits cloud egress;
- face enrollment/approval operations, so camera capture and the face library
  cannot disagree about ownership.

Raw frames stay memory-only by default. Persist only approved face embeddings
and deliberately retained visitor crops, with retention controls. Continuous
inference is local; cloud VLM description is opt-in and never part of ambient
context.

## Harness required before enabling always-on vision

- Contract tests for the versioned `state.vision` and RPC schemas.
- Recorded local fixture clips for empty room, owner, visitor, low light,
  gestures, sleep posture, occlusion, and camera reconnect; CI never needs real
  hardware.
- Deterministic fake analyzers for event ordering, burst collapse, stale-state
  behavior, and owner/visitor fusion with BLE/mmWave/OwnTracks.
- A one-camera-owner test proving Gateway does not open the camera while a
  fresh sidecar lease is active, and safely falls back when it expires.
- Privacy tests that fail on ambient network egress or full-frame disk writes.
- Native Windows soak measurements for camera reconnect, suspend/resume,
  darkness, CPU/RAM, inference latency, and false gesture/presence rates.

Until those contracts exist, keep the current Gateway vision on-demand and do
not claim Smart Room provides continuous vision.
