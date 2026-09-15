# Backlog — big

New subsystems. Each needs its own phase file, owner design approval, and
real-host evidence before it is called done.

## B1. Speaker verification for spoken approvals

**Why.** Confirm mode accepts a spoken "yes" (`AGENTS.md`, tool confirmation
modes). Nothing checks who said it: a guest, a call on speakerphone or a TV can
approve sending, deleting or overwriting. Smart Room knows faces; voice knows
nobody. This is the one security gap in the list.

**Upstream.** `k2-fsa/sherpa-onnx` (Apache-2.0, already evaluated as the STT
packaging fallback) ships speaker-embedding extraction and a speaker-ID API with
3D-Speaker / WeSpeaker ECAPA models; CPU is enough for one 2-second clip.

**Plan.**
1. Interim, before any model: a setting that makes a spoken approval of a
   `sensitive` tool also require the Island tap (voice proposes, the Island
   confirms). Small, and it closes the hole while the rest is built.
2. Enrolment in Setup: three short phrases, embedding stored locally, encrypted
   with DPAPI like other local secrets.
3. The Agent keeps the last approval utterance's audio (already in memory for
   STT), embeds it, and sends a similarity score with the approval.
4. Gateway `take_confirmation` accepts a spoken approval only above a threshold;
   below it the Island asks. The score and threshold are in the audit record.
5. Measure false-accept / false-reject on the owner's voice, a second person,
   and TV audio; pick the threshold from data, not a default.

**Done when.** A second speaker and a recorded clip of the owner played from a
phone are both refused on the RTX 3060 host; the owner is accepted ≥ 95% in a
quiet room; latency added to an approval ≤ 150 ms.

**Not planned.** Diarising whole conversations; identifying guests by voice;
using the voiceprint for anything but approvals.

## B2. Phone companion

**Why.** From a phone Marvi is Telegram text and voice notes. OpenClaw has
iOS/Android nodes with live voice, camera, location and screen.

**Upstream.** `livekit/client-sdk-js` (already a dependency) in a PWA; LiveKit
server already runs locally. Tailscale for off-LAN reach (the user's own
tailnet, no Marvi relay).

**Plan.**
1. Gateway serves a minimal PWA (voice button, transcript, approvals) on an
   opt-in LAN listener; pairing by QR carrying a short-lived join token.
2. LiveKit binds LAN as well as loopback only while a phone is paired;
   credentials per device, revocable from the control center.
3. Approvals appear on the phone with the same token contract as the Island.
4. Second step: phone as a *node* — share location, a camera frame or a photo
   into a turn, each an explicit user action.
5. Off-LAN: documented Tailscale setup; no public listener, ever.

**Done when.** Owner talks to Marvi full-duplex from the phone on Wi-Fi with
interruption working, approves a sensitive action from it, and revoking the
device ends its session within one second.

**Not planned.** Native app-store apps; push notifications through a vendor
relay; anything that needs a public URL.

## B3. Sandboxed code execution

**Why.** `terminal_run` runs on the host with the user's rights. Hermes has a
Python `execute_code` plus Docker/SSH/Modal backends; OpenClaw has sandboxing.
Marvi has no place to run code it does not trust.

**Upstream.** Windows Job Objects (limits, kill-on-close) and AppContainer
tokens are the native options; Docker/WSL are ruled out by Phase 0 (no WSL2 or
Docker dependency). `uv` already builds isolated environments.

**Plan.**
1. Spike: run `python -I` inside a Job Object with CPU/memory/time caps, a
   scratch working directory, and an AppContainer token with no file or network
   capabilities; record what breaks (package imports, temp dirs).
2. `code_run` tool: code in, stdout/stderr/files out, results enveloped as
   untrusted; no confirmation needed because nothing escapes the box.
3. Optional network capability per call, which *does* need confirmation.
4. Harvi can use it for experiments without touching the workspace.

**Done when.** A script that tries to read `%USERPROFILE%`, write outside its
directory, open a socket, or allocate 8 GB is stopped by the OS on the target
host, and a normal pandas script runs.

**Not planned.** Containers; remote sandboxes; GPU inside the sandbox.

## B4. Command checkpoints (*extends #1*)

**Why.** Shipped checkpoints cover Marvi's file tools only. A `terminal_run`
`git reset --hard`, `rm`, `Move-Item` or `>` redirect still destroys work with
no copy. Hermes snapshots before destructive commands into one shared shadow git
store (`~/.hermes/checkpoints`), never touching the project's own `.git`.

**Upstream.** Git itself (already required); Hermes' checkpoint manager as the
design reference (MIT).

**Plan.**
1. A shadow repository under `%LOCALAPPDATA%\Marvi OS\checkpoints\store`, one
   worktree per workspace root, `GIT_DIR`/`GIT_WORK_TREE` so the user's repo is
   untouched; honour `.gitignore`, cap file size.
2. Classify destructive commands (the Hermes list, plus PowerShell verbs
   `Remove-Item`, `Move-Item`, `Set-Content`, `Out-File`, `Clear-Content`).
3. Snapshot before them; `file_checkpoints` lists both kinds; `file_restore`
   restores a file or the whole tree, with a diff preview first.
4. Migrate the flat-file checkpoints into the store; keep the tools' names.

**Done when.** `terminal_run "Remove-Item -Recurse src"` followed by a restore
brings back the folder byte-for-byte, and the user's `.git` has no new objects.

**Not planned.** Checkpointing programs Marvi did not start.

## B5. Meeting assistant

**Why.** OpenHuman joins Meet/Zoom/Teams and transcribes. Marvi sees the
calendar and nothing of the meeting.

**Upstream.** `python-sounddevice` (already a dependency) for WASAPI loopback
capture; the adopted Parakeet TDT worker for transcription; the existing
`vision`/aux model roles for summarising.

**Plan.**
1. Calendar-aware prompt on the Island when a meeting with a video link starts:
   "Take notes?" — never automatic.
2. Capture system output (loopback) and the microphone as two streams; a
   visible recording indicator for the whole session.
3. Local transcription in chunks; speaker turns by stream (you vs. them).
4. At the end: summary, decisions, action items into Chat and Cortex, with the
   transcript attached; action items can become Jobs-board cards (Phase 17).
5. A plain notice about recording consent, shown the first time.

**Done when.** A 30-minute Teams call on the target host produces a transcript
with WER measured against a hand transcript and a summary the owner rates
usable, with voice latency unaffected during the call.

**Not planned.** A bot that joins the call as a participant; cloud
transcription; recording without the indicator.

## B6. Automations and inbound webhooks

**Why.** Cron, Composio triggers and the Mind exist, but the user cannot write
"when X, do Y", and nothing outside can poke Marvi. OpenHuman has workflows,
OpenClaw webhooks.

**Upstream.** APScheduler (adopted) for time triggers; the Gateway journal as the
event bus; FastAPI for the webhook route.

**Plan.**
1. `automations` table: trigger (`schedule`, `room:<kind>`, `account:<trigger>`,
   `app_focus`, `webhook:<id>`), optional condition (a model-free predicate on
   the event payload), action (a tool call, or a prompt to Marvi).
2. Every action goes through `/tools/{name}`, so Confirm/YOLO, audit and
   idempotency apply unchanged.
3. `POST /hooks/{id}` with a per-hook HMAC secret; payload is untrusted and can
   only fill declared fields.
4. Control center page listing automations with last run and a dry-run button;
   Marvi can propose one ("want me to do that every time?") but never enable it
   herself.

**Done when.** "When I sit at the desk after 18:00, turn the room light warm"
and a webhook from a local script both run through confirmation, survive a
restart, and show their runs.

**Not planned.** A visual flow editor; branching workflows; public webhooks.

## Rejected

- **macOS/Linux builds.** Native Windows is the product contract (`AGENTS.md`).
- **The Jobs board** is not here because it already has a plan:
  [Phase 17](../phases/17-kanban.md).
