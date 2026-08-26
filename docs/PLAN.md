# Delivery Plan

Implementation checkpoints and evidence live in [`docs/phases/`](phases/README.md).
The chronological record of completed work lives in
[`docs/IMPLEMENTATION-LOG.md`](IMPLEMENTATION-LOG.md).

## Principles

- Adopt upstream before writing infrastructure.
- Keep the foreground voice path small and measurable.
- Treat the Dynamic Island as the primary product surface.
- Prove native-Windows hardware behavior before committing to a voice engine.
- Tests and documentation ship with every contract.

## Phase 0 — foundations and hardware proof

1. Maintain `AGENTS.md`, architecture, UI contract, decision log, and upstream ledger.
2. Use the installed LiveKit CLI for current official documentation and local
   diagnostics; keep it out of the product UX.
3. Benchmark native streaming STT/TTS candidates on RTX 3060 12 GB.
4. Select models only after latency, quality, VRAM, interruption, and soak gates pass.
5. Audit `D:\smart-room-plugin` bridge/event bus and Marvi's Windows updater.

Exit criteria:

- selected STT and TTS with reproducible measurements;
- no WSL2 or Docker dependency;
- combined always-resident GPU plan leaves required headroom;
- all upstream sources and licenses recorded.

## Phase 1 — upstream scaffold and Marvi Gateway

1. Scaffold the agent worker from LiveKit's official Python starter.
2. Add pinned local LiveKit Server as a supervised dependency.
3. Create the minimal Marvi Gateway facade: health, lifecycle, tokens, status/events.
4. Add version/build metadata and update-check read path.
5. Add process-boundary and recovery tests.

Exit criteria:

- app can start/stop/recover Gateway, LiveKit, and agent worker;
- local room connects through official SDKs;
- no custom audio WebSocket or handwritten RTC lifecycle.

## Phase 2 — desktop shell and Dynamic Island

1. Extract only reusable Island behavior from Marvi, preserving provenance.
2. Build the compact Island state machine defined in `docs/UI.md`.
3. Build the main shell: sidebar, content region, bottom status bar.
4. Add Settings, Activity, Integrations, Room, Memory, Updates, and About shells.
5. Convert the icon source to Windows packaging sizes without using the repo banner.
6. Add visual, state-transition, focus, and idle-cost tests.

Exit criteria:

- closing the main window leaves the Island and local services alive;
- background events never steal focus;
- idle renderer/process/GPU costs are measured;
- About reports version, commit, component versions, and update channel.

## Phase 3 — first complete voice loop

1. Local wake word activates a local LiveKit AgentSession.
2. Selected streaming STT feeds partial/final transcripts through an adapter.
3. OpenCode Go streams the configured conversational model.
4. Selected streaming TTS publishes audio through the LiveKit adapter.
5. Keep capture active during playout; enable WebRTC AEC/noise suppression, pin
   local `TurnDetector v1-mini`, and keep interruption/playout owned by LiveKit.
6. Disconnect/rearm returns to always-on local wake mode.

Exit criteria:

- tested wake → listen → think → speak → interrupt → rearm loop;
- real speaker double-talk test with no self-transcription;
- real microphone/speaker hardware test, not only mocks;
- latency metrics visible in diagnostics;
- 60-minute duplex soak without leaked sessions or growing VRAM.

## Phase 4 — tools, confirmation, and Smart Room

1. Implement the narrow structured tool router.
2. Add Confirm and YOLO modes with append-only audit events.
3. Connect the existing Smart Room sidecar through its audited interface.
4. Display room state/events in the main window and Island micro-events.
5. Add spoken and Island confirmation resolution.

Exit criteria:

- exact-argument confirmation tokens;
- YOLO executes without confirmation and is visibly persistent;
- room sidecar restart/reconnect is loss-aware;
- failures do not interrupt ordinary voice conversation.

## Phase 5 — Composio world context and memory

1. Integrate Composio SDK and its supported account catalog.
2. Add bounded connection/status UI and on-demand retrieval tools.
3. Add writes with Confirm/YOLO behavior and audit records.
4. Select and integrate a memory foundation after an upstream bakeoff.
5. Add event ingestion and a small current-world summary.

Implemented extension: built-in Composio Connect lifecycle, dynamic scoped tool
broker, six native memory providers with per-connection cursor/health state,
and realtime/signed-webhook trigger ingestion into ARC.

Exit criteria:

- external data is never blindly injected into the prompt;
- read/write flows are tested with account sandboxes;
- reconnect, revoked OAuth, duplicate writes, and idempotency are covered.
- Chat and Voice share dynamic account-tool schemas and the Gateway policy path;
- Gmail, Calendar, Slack, Notion, GitHub, and Drive sync independently and a
  failing provider remains visible without stopping the others;
- trigger payloads are deduplicated, enveloped, and journaled as untrusted.

## Phase 6 — proactive behaviour and the mind

1. Journal every event that could make Marvi act, with provenance and trust.
2. Encode the proactivity contract as ordered, named rules.
3. Decide the least intrusive useful surface and record why.
4. Speak proactively without borrowing the full-duplex streaming stack.

## Phase 7 — first Windows release

1. Extract/adapt the tested the predecessor assistant Windows update handoff.
2. Test updates from multiple older releases and interrupted updates.
3. Package and publish the first Windows release.

The durable job bridge to Marvi Agent was dropped from this phase; see
`phases/07-release.md`.

## Phase 8 — vision

1. Keep Smart Room's local presence/gesture inference resident.
2. Consume only bounded facts and structured events through the sidecar contract.
3. Keep raw frames and embeddings out of Gateway and foreground context.
4. Present vision through the existing Gateway runtime and room pipelines.

## Phase 9 — providers, auxiliary models, and identity

1. One `providers/` package as the single source of truth; nothing about a
   provider hardcoded anywhere else, everything editable from the GUI.
2. Three access paths: metered APIs, subscription plans over OAuth, and local
   endpoints. The same vendor may appear on more than one path.
3. Budget control denominated in tokens, because credit, dollar caps and rolling
   windows cannot be compared and mostly cannot be read back. Credit and window
   limits are displayed, not used for control.
4. `SOUL.md` and `USER.md`, composed into the prompt under a token budget.
5. Every background cognition call declares `job="aux"`: ARC mind/presence use
   the `mind` role, reflection uses `memory`, and Auto resolves to the active
   provider's auxiliary default rather than its main conversation model.

Full plan and research in `phases/09-providers-identity.md`.

## Phase 10 — logging, Doctor, and staying up

1. One log file per subsystem — gateway, providers, voice, vision, room,
   desktop, setup — plus `errors.log` collecting warnings and above from all of
   them. The split exists because a merged log is unreadable within a day, and
   `errors.log` is the file that answers the question people actually have.
2. Doctor lives **inside** Marvi, as a Gateway module and a page — not a script
   beside it. A separate script is a second implementation of the same
   knowledge, and the second implementation always drifts.
3. Every finding carries a remedy of one of three kinds: automatic, one click,
   or yours to do. The line: anything that spends money, takes real time,
   downloads at scale, or touches another process is a decision, not a repair.
4. Retry is bounded, jittered, and never applied to an external write.
5. ARC/provider diagnostics correlate jobs and calls with route, model, timing,
   usage, counts, and outcome while excluding prompts, completions, memory
   bodies, and account payloads.

6. `SOUL.md` ships with Marvi and Marvi never writes it; `USER.md` starts empty
   and Marvi fills it by listening, asking at most one rationed question when
   the moment suits.

Full plan in `phases/10-resilience.md`; identity in `IDENTITY.md`.

## Phase 11 — setup

1. One engine in `marvi_gateway/setup/`, two thin front ends: the desktop app
   over HTTP and a `marvi` CLI in-process. A CLI over a shared module is not a
   second product; a PowerShell script would be a second implementation.
2. A CLI is necessary because the desktop app cannot fix the desktop app —
   which is exactly the failure that started Phase 10.
3. Every component is a manifest entry with a hash, generalising
   `config/voice-models.json`. Installs are verified, resumable, idempotent and
   reversible.
4. Models are data; skills and MCP servers are not. Adding an MCP server names
   the command that will run, and a skill cannot grant itself tools.

Full plan in `phases/11-setup.md`.

## Phase 13 — optional messaging companion

1. Pin the complete Marvi Agent messaging repository rather than extracting a
   coupled subset of adapters and gateway code.
2. Give it an isolated profile and explicit opt-in lifecycle under Electron.
3. Reuse its setup, sessions, platform tools, approvals, delivery, and recovery
   unchanged while keeping it outside the LiveKit voice runtime.
4. Make source provenance, configuration state, adapter inventory, and process
   failures visible in Settings → Messaging.

Full acceptance boundary in `phases/13-messaging-companion.md`.
