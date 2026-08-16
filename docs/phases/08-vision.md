# Phase 8 — Vision

**Status:** complete
**Depends on:** Phase 3 media path, Phase 6 proactivity policy

Split out of Phase 6 so the proactive mind could ship without waiting on camera
work. Phase 6 is now cognition only; everything involving a camera lives here.

## Scope

- Always-on local presence and gesture inference with bounded resource use.
- Raw camera frames remain local; selected frames publish only for an explicit
  active vision task.
- Vision context tasks that do not bloat the foreground agent.

## Acceptance evidence required

- ~~A vision event reaching the mind obeys the Phase 6 policy~~ — visitor
  reports are journalled and pass the same surface ceiling and rules.
- ~~Camera privacy boundary~~ — the vision module contains no HTTP client,
  socket, or upload path, asserted by a test that fails if one is ever added.
- ~~Idle cost~~ — an empty room gates 83% of frames and runs no model on them;
  vision is CPU-only, so the GPU budget is structurally untouched.
- ~~Room control obeys the sleep rule~~ — enforced at the boundary for every
  caller, including YOLO.

## Still required

Two items are deliberately not done, and neither is a matter of effort:

- **Recognition accuracy is unvalidated.** `OWNER_THRESHOLD` and
  `KNOWN_THRESHOLD` are literature defaults. Validating them needs the owner's
  face enrolled and a sample of real sightings — the owner's biometric data,
  which is theirs to provide. Everything is in place: `vision_enroll_owner`
  captures samples, and the thresholds are two constants.
- **Activity awareness inside applications.** ActivityWatch reports the window,
  not the work. Seeing inside an application means either per-app integrations
  or screen capture and a vision-language model, which is a privacy decision
  and a subsystem of its own rather than a gap in this one. It belongs in its
  own phase with its own consent story.

Scene description by VLM is not implemented either. Faces are recognised;
scenes are not narrated. The deliberation seam in Phase 6 already accepts a
model, so a captioner can be added there without touching the camera path.

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
| Live camera, empty room | 6 frames, 1 analysed, **5 skipped (83% gated)**, no faces, no thumbnails written — twice |
| Sleep: light on -> off | permitted, reaches the sidecar |
| Sleep: light off -> on | refused, sidecar never called |
| Sleep: brighten | refused |
| Sleep: change mode | refused |
| Sleep under YOLO | still refused |
| Sleep with the sidecar unreachable | still refused; the guard falls back rather than opening |
| Live room (mode `focus`) | all three actions allowed, as expected outside sleep |
| Privacy | the vision module contains no network client at all, asserted structurally |
| Gestures | admitted only when they carry a command |

25 vision tests. A real defect caught live: loading buffalo_l inside the
capture loop consumed the entire observation window, so the first `observe`
returned a single frame. The model is now warmed before the clock starts.

## The sleep rule

While the room is in sleep mode it belongs to the person in it. Marvi may take
exactly one action: switch a light off. Everything else — turning a light on,
brightening it, changing the mode — is refused.

The rule is not "never act", because the one case worth acting on is a light
left on over someone who is asleep. Its worst outcome is a dark room someone
was already sleeping in.

It is enforced at the room boundary rather than in any caller, so it binds
voice, the mind, vision, and YOLO identically. **YOLO removes the prompt, never
the protection** — there is a test asserting exactly that. Live state is read
first; if the sidecar is unreachable the guard falls back to the last snapshot
rather than opening up, because a stale "awake" reading is the one error that
would let Marvi act during sleep.

## Gestures

Marvi consumes the room sidecar's gesture inference rather than running a
second pipeline for it. A bare gesture is ignored — it fires in bursts and
means nothing — but a gesture carrying a `command` is a deliberate instruction
from someone in the room, so those are admitted and capped at Activity.

## Notes

The smart-room sidecar already performs its own vision inference and emits
`vision_identity_state`, `vision_gesture`, and `vision_sleep_state` events. Those
were measured as the dominant event volume — 446 of a 500-event sample — and are
deliberately filtered out of the notable set today. This phase should decide
whether Marvi grows its own camera pipeline at all, or whether it consumes the
sidecar's and simply promotes selected vision events into the journal.
