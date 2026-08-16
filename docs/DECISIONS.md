# Architectural Decisions

## ADR-001 — Separate product from Marvi Agent

**Decision:** Marvi OS is an independent repository and runtime. Marvi Agent is
an optional durable deep-work delegate.

**Reason:** Ambient voice lifecycle must remain available while coding/deep work
is busy and must not inherit the large agent core or tool schema.

## ADR-002 — Local LiveKit managed by Marvi Gateway

**Decision:** Initial releases use a local loopback LiveKit server supervised by
Marvi Gateway. No Cloud mode is implemented.

**Reason:** The product is single-machine, local-first, and always on. LiveKit
still owns RTC/session behavior; Marvi Gateway owns branding and lifecycle.

## ADR-003 — Native Windows only for the voice runtime

**Decision:** WSL2 and Docker are not runtime requirements. Full Unmute is
therefore rejected for shipping. Standalone Kyutai models may ship only if they
pass native-Windows RTX 3060 tests.

**Voice candidates:** Moonshine Voice is the first STT candidate, with
sherpa-onnx as the packaging fallback and newer NVIDIA streaming models as a
quality challenger. Kyutai delayed-stream TTS is tested first, followed by
VibeVoice-Realtime 0.5B. Whisper-family STT and Qwen3-TTS are explicitly
rejected.

## ADR-004 — Electron shell with process-isolated intelligence

**Decision:** Use Electron + React for UI reuse, LiveKit browser compatibility,
and delivery speed. Audio, vision, models, tools, and lifecycle stay outside the
renderer.

## ADR-005 — Dynamic Island is primary

**Decision:** The Island is the always-present interaction surface. The main
window is a control center with sidebar and status bar, not chat.

## ADR-006 — Monochrome ASCII identity

**Decision:** Runtime UI uses monochrome ASCII construction with restrained blue
status accents. The provided square portrait is the app icon source. The wide
banner remains repository-only artwork and is never shown inside the app.

## ADR-007 — External services remain external

**Decision:** Smart Room stays at `D:\smart-room-plugin`; Composio supplies
supported account connectors; memory uses an upstream foundation after
evaluation. Marvi OS uses thin adapters and structured contracts.

## ADR-008 — Model-driven confirmation plus explicit YOLO

**Decision:** In Confirm mode the LLM decides when to ask, and voice or Island
approval resolves the exact action token. YOLO mode bypasses all confirmation,
including risky actions, while retaining validation and audit logging.

## ADR-009 — Repository-owned updates

**Decision:** Reuse Marvi/Hermes' Git-aware, checkout-owned Windows PowerShell
handoff rather than introducing an unrelated generic updater. Product version,
commit, and update channel are visible in About and the status bar.

## ADR-010 — LiveKit behavior is documentation-verified and tested

**Decision:** The LiveKit Agents skill governs LiveKit work. API use is verified
against current official docs, voice context stays minimal, complex work uses
tasks/handoffs, and every agent behavior change includes tests.

## ADR-011 — Full duplex means continuous double-talk-safe media

**Decision:** Marvi OS keeps microphone capture and streaming STT active during
assistant playback. Browser WebRTC echo/noise cancellation is enabled, LiveKit
VAD owns immediate barge-in detection, and the LiveKit audio turn detector is
pinned to local CPU `v1-mini`. Interruption cancels generation and flushes
playout together.

**Reason:** A fast cascade that alternates recording and playback still feels
like push-to-talk. The acceptance gate is a real loudspeaker double-talk test,
not merely low isolated STT/TTS latency.

## ADR-012 — No product CLI

**Decision:** Marvi OS exposes the Dynamic Island, desktop control center, tray,
and voice—not an end-user command-line interface. `lk` is allowed only as a
developer tool and is never bundled as product UX.

## ADR-013 — Gateway-authoritative, event-driven agency

**Decision:** Marvi Gateway owns assistant state, proactive trigger policy,
confirmation tokens, and the durable event journal. LiveKit owns foreground
duplex conversation. Letta is the primary persistent-mind candidate;
APScheduler supplies time triggers; Composio and MCP supply external actions.

**Reason:** A UI timer or continuous LLM loop can imitate activity but cannot
provide accountable agency. Event-driven cognition is cheaper, testable,
interruptible, and can explain why Marvi spoke or acted.

LangGraph and Temporal are deferred until a concrete durable workflow proves
that Gateway jobs plus LiveKit tasks are insufficient.

## ADR-014 — Local SQLite memory instead of an upstream memory framework

**Decision:** Episodic and semantic memory is a local SQLite database with an
FTS5 index, behind a provider seam in `marvi_gateway.memory`. Letta is deferred
and mem0 is rejected as the default. This supersedes ADR-013's naming of Letta
as the primary persistent-mind candidate; ADR-007's "upstream foundation after
evaluation" is satisfied by this evaluation concluding "not yet".

**Reason:** measured against the ADR-013 and `REAL-AGENCY.md` gates.

- **mem0 2.0.18** hard-depends on `openai`, `qdrant-client`, and `posthog`. A
  local-first product cannot default to a memory layer that ships product
  telemetry and a cloud embedding client.
- **Letta 0.16.8** carries 69 core dependencies including `sentry-sdk`, and is
  itself a server with its own SQLAlchemy/Alembic migrations. That duplicates
  the role `AGENTS.md` assigns to Marvi Gateway.
- Both require an embedding model. Nothing has yet shown that keyword retrieval
  is insufficient, and the RTX 3060 budget already sits at 4.245 GiB with a 2 GB
  headroom requirement.
- SQLite with FTS5 ships in the bundled Python. Measured over 10,000 entries:
  12.94 ms median search, 1.90 MiB on disk, 1.15 ms reopen, 4.07 ms per write
  (one commit per write), zero VRAM, zero new dependencies, zero telemetry.

**Revisit when** retrieval quality measurably fails on real recall tasks. The
store is deliberately narrow — `remember`, `search`, `recent`, `forget`,
`export` — so a vector backend can be swapped in behind it.

## ADR-015 — External content is contained structurally, not by filtering

**Decision:** Every piece of content originating outside this machine is
delivered inside an envelope whose delimiter is a per-envelope random nonce,
carrying its provenance and an explicit untrusted label. Content that arrives
from an account, or is recalled from memory having come from one, is never
handed to the model as bare text. Injection-pattern detection exists only to
show the user what was attempted; it never sanitises and never gates.

**Reason:** a lexical filter is a guessing game the defender loses. An
unguessable delimiter is not guessable by definition, and it keeps working
against phrasings nobody enumerated. Content is preserved verbatim so the user
sees exactly what arrived, and the audit records which injection shapes it
contained.

Memory is part of this boundary. An untrusted memory is stored with
`trusted = 0` and re-enveloped on recall, so an injection cannot launder itself
into instruction position by taking a detour through storage.
## ADR-014 — Frameless shell with renderer-painted chrome

**Decision:** The control center window is frameless and paints its own title
bar (brand, page, window controls). The Hermes hidden-titlebar pattern is
adapted, not the native WCO overlay, because the Marvi OS brand chrome (mono
Collapse type, drag region, custom hover states) is the product surface.

**Reason:** A native title bar breaks the monochrome shell and cannot carry
the brand. The renderer-painted bar keeps one design system; window verbs stay
native via IPC (minimize/maximize/close handled in main with sender checks).

## ADR-015 — Local-only backdrop and chrome assets

**Decision:** Electric Gaze and all Hermes-adapted chrome ship as vendored
local assets or MIT npm dependencies. No runtime CDN fetch; source URLs and
licenses live in the UPSTREAM ledger.

**Reason:** The product contract is local-first and fail-closed. A backdrop
that needs the network violates the always-on promise and the UI contract.
