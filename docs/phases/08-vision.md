# Phase 8 — Vision

**Status:** in progress
**Depends on:** Phase 3 media path, Phase 6 proactivity policy

Split out of Phase 6 so the proactive mind could ship without waiting on camera
work. Phase 6 is now cognition only; everything involving a camera lives here.

## Scope

- Always-on local presence and gesture inference with bounded resource use.
- Raw camera frames remain local; selected frames publish only for an explicit
  active vision task.
- Vision context tasks that do not bloat the foreground agent.

## Acceptance evidence required

- ~~A vision event reaching the mind obeys the Phase 6 policy~~ — done: visitor
  reports are journalled and pass through the same surface ceiling and rules.
- Camera privacy boundary test: raw frames never leave the machine. Frames are
  currently never published anywhere, but this needs stating as a test rather
  than an absence.
- Idle GPU/RAM measurement with the voice stack resident. Vision is CPU-only by
  construction, so the GPU claim is structural; it still wants measuring.
- Face recognition accuracy on real faces. Thresholds are currently
  literature defaults, unvalidated against this camera and this room.

## Still required

- **Recognition accuracy is unvalidated.** `OWNER_THRESHOLD` and
  `KNOWN_THRESHOLD` are untuned defaults; they need a real enrolment and a
  sample of real sightings before they can be trusted.
- **Gesture and pose are not implemented.** The room sidecar already emits
  gestures, so Marvi should probably consume those rather than grow a second
  pipeline — that is the open question below.
- **Room control from vision** is not wired. The mind can already act through
  the tool router, so this is a policy question rather than new plumbing.
- **Activity awareness inside applications** is not addressed. ActivityWatch
  sees the window, not the work; nothing here changes that yet.
- **No VLM scene reasoning.** Faces are recognised, not scenes described.

## Implemented — faces, visitors, and homecoming

`marvi_gateway.vision`, built fresh rather than copied. Four decisions differ
from the reviewed pipeline, each for a reason:

- **Inference is motion-gated.** The reviewed design runs a continuous analysis
  loop, so a camera pointed at an empty room burns CPU forever to learn
  nothing. A cheap frame difference decides whether the model runs at all —
  the same cheap-signals-first escalation `REAL-AGENCY.md` already asks for.
  Measured live: 4 frames captured, 1 analysed, 3 skipped.
- **Everything runs on the CPU.** The voice stack holds 4.245 GiB and
  `AGENTS.md` requires 2 GB of headroom, so vision must not compete for VRAM.
  buffalo_l on CPU measured 124 ms per 640×480 frame, far faster than the
  motion gate will ever ask for it.
- **A face is compared against the owner before it can be a stranger.** A bad
  angle on the owner must not manufacture a visitor, and there is exactly one
  owner because the whole visitor rule is "not the owner".
- **Visitors are held, not announced.** Telling someone about a stranger while
  they are out is useless and slightly alarming. Sightings queue with a cropped
  thumbnail and a timestamp, and surface on the away → home edge through the
  Phase 6 mind, where `vision:visitor_report` is allowed to be spoken.

A lingering stranger is folded into one entry rather than fifty by comparing
against the queued embeddings. Approving a face enrols it, so the same person
is recognised next time instead of queueing again.

## Evidence

| Gate | Result |
|---|---|
| Owner recognised | enrolled owner matches as `owner` |
| Bad angle on the owner | still `owner`, not a manufactured stranger |
| Known but not owner | matches as `known` |
| Unfamiliar face | `unknown`, below the known threshold |
| Lingering stranger | one queue entry, not one per frame |
| Two different strangers | two entries |
| Visitor entry contents | thumbnail path, date, and time |
| Approval | enrols the face and clears the queue |
| Away | nothing announced, queue retained |
| Arrival home | one report with thumbnails, spoken surface allowed |
| Staying home | no repeat report; only the arrival edge fires |
| Missing camera | reported, not raised |
| Live camera | model warm, 4 frames, 1 analysed, 3 skipped by the gate |

25 vision tests. A real defect caught live: loading buffalo_l inside the
capture loop consumed the entire observation window, so the first `observe`
returned a single frame. The model is now warmed before the clock starts.

## Notes

The smart-room sidecar already performs its own vision inference and emits
`vision_identity_state`, `vision_gesture`, and `vision_sleep_state` events. Those
were measured as the dominant event volume — 446 of a 500-event sample — and are
deliberately filtered out of the notable set today. This phase should decide
whether Marvi grows its own camera pipeline at all, or whether it consumes the
sidecar's and simply promotes selected vision events into the journal.
