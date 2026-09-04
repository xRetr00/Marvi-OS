# Phase 8 — Vision

**Status:** implementation complete; native Windows hardware soak pending
**Depends on:** Phase 3 media path, Phase 6 proactivity policy, Smart Room plugin 0.7+

## Decision

Smart Room owns the camera and room-specific vision. Marvi owns and supervises
the sidecar, consumes its authenticated state/tools/events, applies policy, and
presents results. There is no second camera path in Gateway and no plugin UI.

See [VISION-PIPELINE-REVIEW.md](../VISION-PIPELINE-REVIEW.md) for the complete
boundary and privacy invariants.

## Delivered

- One native Windows camera capture/reconnect loop in Smart Room.
- Local InsightFace owner/visitor recognition and MediaPipe gesture/posture
  analysis, with plugin-owned model downloads and data.
- Versioned bounded `state.vision`, authenticated observation/description and
  identity RPC operations, and structured room events.
- Unknown-visitor deduplication and delayed visitor reporting through the room
  presence transition.
- Quality gates keep partial, blurred, low-confidence, and undersized face
  detections out of enrollment and the review queue.
- The pending queue honors the configured retention limit, removes orphaned
  crops, reports the nearest known identity, and supports single or bulk
  rejection without leaving image files behind.
- No raw frames or embeddings in Gateway, prompts, logs, or Electron IPC.
- Gateway no longer installs/imports local vision models or owns a face store.
- Read operations bypass confirmation; enrollment and identity mutations use
  Marvi confirmation policy (or YOLO when enabled).
- Existing Gateway runtime/room-event pipeline feeds the Room page, Vision
  status, status bar, and Dynamic Island. The UI renders structured facts only;
  it has no frame-preview RPC or renderer-to-plugin transport.
- Owner assignment is explicit and stable when adding samples to an existing
  identity. Plugin-declared failures propagate as failed Gateway tool results.
- The Vision page uses a compact six-item paginated review list with clear
  identity, nearest-match, owner, save, reject, and reject-all actions.
- Deterministic fixture tests that do not require a camera or model download.

## Acceptance evidence

| Gate | Result |
|---|---|
| Single camera owner | Gateway vision implementation and model dependencies removed |
| Sidecar contract | state round-trip and authenticated RPC routing covered |
| Owner/known/unknown matching | deterministic embedding tests |
| Lingering stranger | deduplicated into one pending visitor |
| Persistence scope | unknown visitors only; known faces are live state |
| Privacy | descriptions contain facts only, never a frame |
| Context | bounded plugin context, no raw media or event flood |
| Gestures/posture | deterministic analyzer events; posture says resting, not definitive asleep |
| UI | structured Gateway → Electron facts only; no preview transport; compact paginated review list |
| Failure behavior | disabled/unavailable vision degrades without stopping voice or room tools |

## Hardware acceptance still required

The remaining work needs the target camera and owner, so it cannot be honestly
closed by CI:

1. Enrol the owner and calibrate recognition thresholds across lighting and
   viewing angles.
2. Soak camera reconnect across unplug, sleep/resume, and overnight runtime.
3. Measure CPU/RAM, inference freshness, and false gesture/posture events.
4. Verify visitor crops, approval, rejection, and retention with real samples.
5. Confirm the camera indicator follows actual sidecar readiness throughout.

This is calibration of the implemented architecture, not permission to add a
second Marvi camera pipeline.
