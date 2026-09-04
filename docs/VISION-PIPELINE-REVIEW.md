# Vision pipeline ownership and implementation

Status: implemented and reviewed against Marvi OS and the independent Smart
Room repository on 2026-08-23.

## Production boundary

Smart Room is the single owner of the physical camera and all room-specific
vision logic. Marvi does not import a vision model, open the camera, keep a face
database, or infer room state. Marvi owns the sidecar lifecycle and consumes
only its authenticated contract.

```text
Windows camera
  -> Smart Room capture/reconnect loop
  -> local InsightFace + MediaPipe analysis
  -> bounded state.json and structured events.jsonl
  -> authenticated loopback RPC
  -> Marvi RoomSidecar
  -> Gateway tools/runtime/journal
  -> existing Electron IPC
  -> Room page, Vision status, Dynamic Island
```

There is no plugin UI and no direct renderer-to-plugin connection. The desktop
keeps using the normal Gateway pipeline. This preserves one security boundary,
one reconnect policy, one source of truth, and one place for confirmations.

## What Smart Room owns

- The always-on Windows camera handle and reconnect loop.
- Local model download and checks under its plugin-owned data directory.
- Owner enrollment, known identities, embeddings, and visitor approval.
- Unknown-visitor crops and their report lifecycle.
- Person count, owner visibility, motion/activity, gestures, and conservative
  posture state.
- Vision freshness, capabilities, errors, and structured room events.

Only unknown visitors are persisted as sightings. Known faces remain live
state, preventing an unbounded surveillance history and constant thumbnail
writes while the owner sits at the PC.

## What Marvi owns

- Installing, starting, supervising, updating, and stopping the sidecar.
- Token-authenticated RPC access and the tool/policy boundary.
- Read-only `smart_room_vision` calls without confirmation.
- Confirmation (or YOLO policy) for `smart_room_vision_identity` mutations.
- Bounded prompt context through the plugin context provider.
- Trusted event journaling, Mind decisions, voice surfaces, and Dynamic Island
  notifications.
- Desktop presentation through the existing `/runtime`, room-state tool, and
  room-event routes.

The former Gateway `VisionService`, `FaceLibrary`, on-demand cloud description,
vision model installer, model dependencies, and Marvi vision paths were
removed. Gateway health now reports the camera facts published by Smart Room.

## Privacy and context invariants

- Raw frames and face embeddings never enter RPC, prompts, the Gateway journal,
  or Electron IPC.
- Ambient vision performs no cloud egress. `vision_describe` summarizes the
  current structured facts; it does not upload a frame to a VLM.
- Context remains a short, bounded plugin line appended after stable identity
  content. Raw logs and high-frequency events are not prompt context.
- `vision_visitor_seen` remains internal to room processing. The user-facing
  `visitor_report` is emitted only at the appropriate presence transition.
- Posture may report `resting`; it does not claim a person is asleep from one
  frame.

## Implemented verification

Smart Room has deterministic tests for state round-tripping, owner preservation,
face matching, nearest-match review data, quality gating, bounded unknown
deduplication, thumbnail cleanup, structured gestures, and the no-frame
description contract. Gateway tests cover plugin-result failures, plugin
context, room-event allowlisting, degradation without the sidecar, and
confirmation policy. No preview method exists in the RPC contract.

## Hardware work still required

Automated fixtures prove contracts, not camera quality. Before treating vision
as production-calibrated, run a native Windows soak on the target PC for:

- camera reconnect after unplug, suspend/resume, and app restart;
- owner/visitor accuracy in daylight, darkness, occlusion, and side profiles;
- gesture false positives and posture stability;
- CPU/RAM use and frame freshness over an overnight run;
- retention and approval behavior for real unknown visitors.

Those measurements tune the sidecar configuration. They do not change the
ownership or UI architecture above.
