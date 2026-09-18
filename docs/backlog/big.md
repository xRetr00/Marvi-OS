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

**Why.** `terminal_run` runs on the host with the user's rights. OpenClaw has sandboxing.
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
no copy.

**Upstream.** Git itself (already required).

**Plan.**
1. A shadow repository under `%LOCALAPPDATA%\Marvi OS\checkpoints\store`, one
   worktree per workspace root, `GIT_DIR`/`GIT_WORK_TREE` so the user's repo is
   untouched; honour `.gitignore`, cap file size.
2. Classify destructive commands, including PowerShell verbs
   `Remove-Item`, `Move-Item`, `Set-Content`, `Out-File`, `Clear-Content`.
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

## B7. macOS and Linux builds

**Why.** The owner wants Marvi on macOS and Linux alongside Windows, not
instead of it. This reverses the entry that used to sit under Rejected, so the
first item below is a contract change rather than code: `AGENTS.md` opens with
"an always-on **Windows** voice and vision assistant", and until the owner
edits that line, everything here is a plan and nothing is a commitment.

**What is actually in the way.** Not the Electron app -- that is portable
already, and `electron-builder.yml` has carried `mac`, `dmg`, `linux` and
`appImage` blocks since the template. What is in the way is everything that
reaches the machine:

| What | Where | On another OS |
| --- | --- | --- |
| Wake word host | `apps/wake-host` (Rust, `windows-sys`) | The ONNX model and the audio loop are portable; the tray, the single-instance mutex and the session hooks are not. |
| Desktop companion | `apps/pet-host` (Rust, `windows-sys`) | A click-through always-on-top layered window. macOS wants `NSWindow` with `ignoresMouseEvents`; Wayland has no equivalent at all, so X11 only or nothing. |
| Location | `apps/location-host` (Rust, WinRT `Devices.Geolocation`) | macOS has Core Location. Linux has no OS geolocation; it would stay IP-only, which is what this machine already does. |
| Updater | `apps/updater` (Tauri) + NSIS handoff | A `.app` updates by replacing a bundle; an AppImage by replacing a file; a `.deb` by the distro's package manager, which Marvi must not fight. Three different stories, none of them the NSIS one. |
| App focus, idle, quiet hours | `focus.py`, `desk.py` | `SHQueryUserNotificationState`, WNF and `keybd_event` have no portable equivalent. macOS: `NSWorkspace` + `CGDisplay`; Linux: whatever the desktop exposes, which is not a promise. |
| Volume, media keys | `desk.py` (Core Audio COM) | macOS: `AudioToolbox`. Linux: PulseAudio/PipeWire over D-Bus. |
| Sandbox limits | `sandbox.py` (Job Objects) | `setrlimit` on both, which is *simpler* than the Windows path. |
| Local secrets | Electron `safeStorage` | Already portable: Keychain on macOS, libsecret on Linux. Nothing to do but test that libsecret is actually present.
| Global hotkeys | `main/hotkeys.ts` | Electron `globalShortcut` is portable, but macOS refuses to register until Accessibility is granted, and Wayland refuses full stop. |
| Computer use | Cua | Has macOS and Linux backends; this is the one native capability that gets *easier*. |
| Build and release | `scripts/*.ps1` | PowerShell Core runs everywhere, but code signing does not: macOS needs a Developer ID and notarisation, and unsigned is a Gatekeeper wall rather than a warning. |

**Plan.** In the order that keeps a half-finished port honest rather than
mysteriously broken:

1. **Say what a platform is.** One capability table the Gateway serves and the
   window reads, so a missing capability is a greyed control that says "not on
   macOS" rather than a tool that fails at the moment of use. Nothing else in
   this list should start before this does.
2. **Split the platform code behind it.** `focus.py`, `desk.py`, `parent.py`,
   `workspace.py`, `sandbox.py` and `wake.py` each grow a `_windows.py` and a
   `_posix.py` beside a small interface. The Windows path must not change
   behaviour: the port is a refactor first, and a refactor that breaks the
   working platform to reach a new one has traded down.
3. **Linux first, not macOS.** CI can run it, an AppImage needs no signing
   authority, and `setrlimit` and D-Bus are the least surprising of the two
   sets. Target X11 for the companion and say so; Wayland is a separate
   decision, not a bug report.
4. **macOS second, entitlements first.** Camera, microphone, Accessibility and
   Screen Recording are four separate prompts and the app is useless until all
   four are answered. Setup has to ask for them in order and verify each,
   because a denied prompt on macOS is silent.
5. **Updater per platform.** macOS: Sparkle-style bundle replacement, signed.
   Linux: AppImage replacement for AppImage, and *nothing* for `.deb` -- a
   packaged Marvi is the distro's to update, and an app that fights its package
   manager is a bug.
6. **CI that builds all three** on every tag, with the platform test suite
   green on each. A platform nobody builds on a schedule is a platform that is
   already broken.

**Done when.** A fresh macOS and a fresh Ubuntu host each run Setup, hold a
voice conversation, approve a sensitive tool, and survive a restart with the
jobs board intact -- and every capability the host does not have is greyed out
with a reason before it is reached, rather than failing when it is.

**Not planned.** Feature parity as a promise. Some things do not port and
should be said rather than faked: the desktop companion under Wayland, OS
geolocation on Linux, and any capability that would need a kernel extension.
Windows stays the reference platform -- it is the one the owner runs, and the
one the evidence in `docs/` is from.

## Rejected

- **The Jobs board** is not here because it already has a plan:
  [Phase 17](../phases/17-kanban.md).
