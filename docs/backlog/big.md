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

## B3. Sandboxed code execution — shipped 2026-09-19

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

**Shipped.** `sandbox.py`, tool `code_run`, `test_sandbox.py`. A Job Object with
`PROCESS_MEMORY`, `ACTIVE_PROCESS` and `KILL_ON_JOB_CLOSE` caps memory at 512 MB
and the tree at four processes; the child runs `python -I` in a scratch
directory that is deleted after, with a preamble that removes `socket`, and its
output comes back enveloped as untrusted.

**The AppContainer, 2026-09-19.** `lowbox.py`. A lowbox token with no
capabilities, launched through `CreateProcessW` with
`PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES`, so the kernel refuses the handle
rather than a wrapper refusing the call. Every gate in the acceptance was met on
the owner's host against the packaged interpreter:

| What the snippet tried | What happened |
| --- | --- |
| List `%USERPROFILE%` | `PermissionError: [WinError 5] Access is denied` |
| Read `D:\Marvi-OS\README.md` | `PermissionError: [Errno 13]` |
| Write `C:\Users\xRetro\marvi-escape.txt` | `PermissionError`, and the file does not exist afterwards |
| `connect()` to 1.1.1.1:443 through `ctypes`, bypassing the interpreter guard | `WSAEACCES (10013)` -- the firewall, not Python |
| `bytearray(8 GB)` | `MemoryError` from the Job Object |
| A pandas script | ran; pandas 3.0.5 imported, wrote its file |

**It does not always engage, and it always says which.** A Python installed for
every user cannot be granted to the container -- changing a DACL under
`C:\Program Files` needs rights Marvi does not ask for -- so on a machine like
that this falls back to the Job Object alone and the result says
`isolation: job` with the reason. The packaged product is unaffected: its
interpreter is under `%LOCALAPPDATA%` and `%APPDATA%`, which the owner owns.

Two things cost an hour each and are in the tests rather than in a comment: a
container launch needs the profile variables in its environment or
`CreateProcessW` answers `ERROR_ENVVAR_NOT_FOUND` with no hint why, and
`icacls /T` silently drops an ACE carrying `(OI)(CI)` when it reaches a file,
so granting a tree takes two passes.

## B4. Command checkpoints (*extends #1*) — shipped 2026-09-18

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

**Shipped.** `treecheck.py`, wired into `workspace.run`, `test_treecheck.py`.
A bare repository per workspace root under the checkpoint store, addressed by
the SHA-256 of the root path, with `GIT_DIR`/`GIT_WORK_TREE` pointing at it, so
the user's own `.git` gains nothing. `looks_destructive` classifies the
PowerShell verbs as well as the Unix ones; `file_checkpoints` lists file and
tree snapshots together and `file_restore` takes either kind.

## B5. Meeting assistant — shipped 2026-09-19

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

**Shipped.** `audiocapture.py`, `meetings.py`, the `/meetings` routes, the
Meetings page, the status-bar indicator, `test_meetings.py`.

**Loopback is ctypes, not the audio library.** `sounddevice` is already a
dependency and its API has the option, but the PortAudio it ships
(V19.7.0-devel) does not carry the flag -- `WasapiSettings(loopback=True)` is a
`TypeError`, not a recording. So WASAPI directly, the same way `desk.py` reaches
the volume control, with the microphone on the same path so there is one
mechanism rather than two. Verified by playing a 440 Hz tone and measuring the
captured spectrum: 440.0 Hz, which a stream that silently records nothing
cannot produce.

**Recorded live, transcribed afterwards.** The plan said transcription in
chunks; the acceptance said voice latency must be unaffected during the call.
Two 0.6B recognisers running for thirty minutes on the card that is also
carrying the voice session cannot honour the second. So the call costs two WAV
writers, and the work-up happens when it ends -- each side cut into 30-second
windows, silence skipped, windows interleaved by timestamp. Speaker turns come
from *which stream it arrived on*, which is exact rather than inferred.

**The offer is on the Meetings page, not the Island.** The plan said the Island;
what shipped is a card on the page the status-bar indicator already points at,
carrying the same Record control. It is fed from the calendar cache the Voice
page fills and **never fetches**: this route is polled while the page is open,
and a calendar lookup is a request to somebody else's API. A cold cache means
no offer, which is the right way round -- a missing offer is a convenience
nobody got, and a fetch per poll is a bill. The Island version is a smaller
piece of work on top of , which is built and tested.

**Two defects in the existing recogniser were found doing this**, both fatal in
the same unhelpful way -- the worker dies and the caller sees only "speech
runtime closed". It cannot take a 64 KiB chunk (16,000 bytes goes through), and
it dies on flush past about twelve seconds of audio. Both were reaching Telegram
voice notes and chat dictation too. `transcribe_for_channel` now feeds
`dictation.CHUNK_BYTES` and keeps the last cumulative partial when flush dies;
the runtime itself still needs fixing.

## B6. Automations and inbound webhooks — shipped 2026-09-18

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

**Shipped.** `automations.py`, the `/automations` and `/hooks/{id}` routes, the
Workflows page, `test_automations.py`. Every action runs through
`run_tool_for_automation`, which is the ordinary validate → audit → confirm →
execute path, so a sensitive action fired by a webhook still waits for the user.
A rule Marvi proposes is written disabled whatever `enabled` says, and one rule
may fire sixty times an hour before it is rate-limited and told so in its own
history.

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

## B8. The product in another language, starting with Arabic

**Why.** Marvi already lets you choose what she *listens* for and what she
*answers* in -- `language.py`, Understand and Speak. That is the conversation.
It is not the product: every label, every button, every settings page and every
error is English, hard-coded in the file that draws it. The owner wants the
whole thing in Arabic, and Arabic first deliberately, because it is the one
that breaks the most assumptions. Anything that survives Arabic will survive
French.

**What "another language" actually means here.** Marvi has three kinds of text
and they need three different answers. Conflating them is how this goes wrong:

| Kind | Where | What it needs |
| --- | --- | --- |
| **Model-facing** | `prompts/`, tool descriptions, `describes` | **Stays English.** These are instructions to a model that reads English best, and translating them costs accuracy for nothing -- the *answer* is what the user reads, and that is settled by `language.reply_instruction()`. |
| **UI chrome** | ~100 files under `apps/desktop/src/renderer` | A catalogue, and the mechanical work of getting the strings out of the JSX. |
| **Marvi's own words** | her replies, what she speaks, `announce.py`, error text that reaches a person | The model already writes these in the Speak language. What does not is the prose the Gateway composes itself, and that is a smaller list than it looks. |

**Why Arabic is the hard one.** Not the translation. Nine things, and the first
four are why "just add a strings file" is not the plan:

1. **Direction.** Every layout in the app is authored left to right, in
   physical CSS -- `margin-left`, `padding-right`, `text-align: left`,
   `left: 0`. An RTL document needs the logical forms (`margin-inline-start`,
   `inset-inline-start`), and that is a sweep of `main.css`, not a switch.
   The Dynamic Island, the sidebar, the chat gutter and the status bar all have
   a handed geometry that has to mirror.
2. **Bidi.** Arabic text with a Latin run inside it -- a file path, a model
   name, `code_run`, a URL -- reorders on screen unless each run is isolated.
   Marvi's UI is full of exactly that mix. Without `<bdi>` or the isolate
   characters, a path inside an Arabic sentence renders with its parts in the
   wrong order, and it looks like a bug in the path rather than in the text.
3. **Shaping and fonts.** Arabic letters join, and the three fonts Marvi ships
   -- the display face, the body face and `--ui-font-mono` (JetBrains Mono /
   Geist Mono) -- have no Arabic coverage at all. Monospace is the sharp one:
   there is no good monospaced Arabic, so a transcript or a tool result in a
   mono block needs a paired Arabic face and a decision about what "monospace"
   means when half the line cannot be.
4. **Numerals and formats.** Arabic-Indic digits (٠١٢٣) or Western, per locale
   and sometimes per user; `Intl.NumberFormat` and `Intl.DateTimeFormat` with
   the right locale rather than the hand-rolled formatting the pages do now.
   Times, durations and "3 minutes ago" all go through this.
5. **Recognition.** Arabic is **not** in `parakeet-tdt-0.6b-v3`'s 25 languages
   (see `language.RECOGNISED`) and `nemotron-3.5` is English. There is no
   Arabic speech recognition in Marvi today, and no setting can pretend
   otherwise. A model has to be chosen, measured and packaged.
6. **Voice.** Kokoro has no Arabic voice, and `language.speakable()` already
   refuses to offer a language it has no voice for -- correctly, because the
   alternative is English phonemes reading Arabic words. Same story: choose,
   measure, package.
7. **Wake word.** The wake model is trained on English pronunciations of the
   name. An Arabic speaker saying it is a different sound, and the false-reject
   rate is the whole feature.
8. **Search and memory.** The FTS5 index tokenises on whitespace and ASCII
   folding; Arabic needs its own normalisation (alef forms, tatweel,
   diacritics) or search finds nothing a person would expect it to.
9. **Calendars.** Hijri dates exist and are used. Out of scope for the first
   pass, and worth saying so rather than discovering it in a bug report.

**Upstream.** No new framework. `Intl` is in the platform and `dir="rtl"` is in
the platform; a translation catalogue is a JSON file and a lookup, and
`react-i18next` would be a dependency for a `t()` function Marvi can write in
fifteen lines. Fonts: Noto Sans Arabic and Noto Kufi Arabic (SIL OFL), vendored
like the existing faces. For recognition and voice the candidates to measure
are `whisper-large-v3` and Meta's MMS for ASR, and XTTS-v2 or a Piper Arabic
voice for TTS -- each on the RTX 3060 budget, against the latency gates the
voice phases already set, and recorded in `UPSTREAM.md` before anything ships.

**Plan.** The order matters: the mechanical part is worth nothing until the
layout part works, and doing it the other way round means translating into a
UI that then has to be rebuilt.

1. **Make the shell right-to-left with no translation at all.** A setting that
   sets `dir` on the document, the physical-to-logical sweep of `main.css`,
   mirrored icons where handedness means something (back, forward, the panel
   toggle), and `<bdi>` around every path, identifier and model name. Read the
   whole app in English-in-RTL and fix what tips over. Nothing is translated at
   this step and that is the point: it isolates the layout bugs from the
   language ones.
2. **A catalogue and a `t()`.** One JSON per language, one flat lookup, English
   as the fallback for a missing key, and a test that fails on a key missing
   from a shipped language. Extraction is the long tail -- do it page by page,
   starting with the ones a person sees first.
3. **Formats through `Intl`.** Numbers, dates, durations and relative times,
   with the locale from the same setting. Replace the hand-rolled formatting
   rather than wrapping it.
4. **Marvi's own prose.** Audit what the Gateway composes itself and reaches a
   person -- `announce.py`, the settings copy the window shows verbatim, the
   error text from tools. Route those through the catalogue; leave everything
   model-facing in English and say so in `AGENTS.md`.
5. **Arabic search.** Normalise alef forms, strip tatweel and diacritics in the
   FTS5 tokeniser path, and test that a word typed without diacritics finds the
   one stored with them.
6. **Then the voice, as its own piece of work.** ASR and TTS models chosen on
   measured gates, not on a model card. Until they land, Arabic is a *reading*
   language in Marvi and the settings page says exactly that -- the same
   honesty `language.py` already applies to Understand.

**Done when.** The whole window reads right to left in Arabic with no Latin
text stranded in the wrong order, a mixed Arabic-and-path sentence renders
correctly, numbers and dates are in the chosen locale, search finds an Arabic
word typed without its diacritics, and every string a person can reach is
either translated or falls back to English visibly rather than showing a key.
Voice has its own gates and its own phase.

**Not planned.** Translating prompts or tool descriptions. A right-to-left
*code* editor. Hijri calendars. Machine-translating the catalogue -- a wrong
label in a settings page is worse than an English one, and the owner speaks
the language.

## Rejected

- **The Jobs board** is not here because it already has a plan:
  [Phase 17](../phases/17-kanban.md).
