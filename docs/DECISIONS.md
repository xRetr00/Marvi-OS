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
