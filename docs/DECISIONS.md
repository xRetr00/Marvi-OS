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

**Decision:** Reuse the predecessor assistant' Git-aware, checkout-owned Windows PowerShell
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

## ADR-014a — Correction: Letta is an LLM provider, not a memory library

**What ADR-014 got wrong.** It evaluated Letta as a self-hosted memory server
and weighed its 69 dependencies against a local store. That is the wrong shape.
The supported integration is `openai.LLM.with_letta(agent_id=..., base_url=...,
api_key=...)`, verified present in the installed livekit-agents 1.6.10. Letta
replaces the **LLM**, serving an OpenAI-compatible chat-completions endpoint
that owns the agent's memory blocks and its sleep-time (background
consolidation) agents. Marvi OS would not import Letta at all.

**What that changes.** The dependency-weight argument does not apply to the
cloud path, and Letta's sleep-time agents are a real implementation of the
consolidation behaviour Marvi wants.

**What it does not change.** Two constraints still bind:

- `with_letta` routes conversation to Letta's endpoint, which by default is
  `https://api.letta.com`. Sending the whole conversation to a third party
  contradicts the local-first contract, and it displaces OpenCode Go as the
  configured provider (ADR-013).
- The self-hosted path avoids that, but is the same 69-dependency server, and
  `LETTA_API_KEY` is not configured on the target machine today.

**Decision:** the local SQLite store stays the default and keeps serving
episodic, semantic, graph, reflection, and consolidation needs. Letta remains a
live candidate for the *mind* rather than the store, to be adopted only behind
a self-hosted `base_url` and only after the `REAL-AGENCY.md` gates are measured
— idle cost, retrieval latency, first-token latency, restart recovery, and
privacy. The reflection seam in `marvi_gateway.memory.reflect(summarise=...)`
exists so an external summariser can be swapped in without touching storage.

## ADR-016 — Tools reach the world through one policy

**Decision:** every tool — room, accounts, memory, web, file, terminal,
process, and MCP — is registered in the Gateway router. MCP servers are
connected as clients by the Gateway rather than attached to the LiveKit `Agent`
via `mcp_servers`, even though the latter is less code.

**Reason:** the router is where confirmation tokens, the audit trail, and
external-write idempotency live. A tool attached directly to the agent skips
all three, so a third-party MCP server could act without a token or an audit
line, contradicting ADR-008. One policy, one place.

Three rules follow from this:

- Anything a tool returns — a web page, a file, another program's stdout, an
  MCP result — is external content and is enveloped (ADR-015).
- An MCP tool is sensitive unless its own annotations declare a read-only hint.
  An unfamiliar server asking to act should ask first.
- Reach is configured, never assumed: file and terminal tools refuse entirely
  until `MARVI_WORKSPACE_ROOT` names a root, web tools refuse until a search
  provider is configured, and every fetched URL must resolve to a public
  address so an agent cannot be talked into reading loopback.

## ADR-021 — Vision is motion-gated, CPU-only, and owner-relative

**Decision:** face recognition runs on the CPU with `buffalo_l`, behind a frame
difference gate, and a face is only a visitor once it has failed to match the
enrolled owner. Sightings queue with a thumbnail and surface when the owner
comes home rather than while they are out.

**Reason:** three constraints, each with a failure mode behind it.

- The GPU budget belongs to the voice stack. It holds 4.245 GiB and `AGENTS.md`
  requires 2 GB of headroom, so a second resident model on the GPU is not
  available. CPU inference measured 124 ms per frame, far below what the gate
  asks for.
- Continuous analysis is the expensive mistake. A camera watching an empty room
  should cost almost nothing, and a frame difference is the cheapest possible
  way to know nothing happened.
- Owner-relative matching prevents the worst failure: a poor angle on the owner
  being announced as a stranger in their own home. There is exactly one owner
  because "visitor" is defined as "not the owner".

Holding visitor reports until the away → home edge is a product judgement:
telling someone about a stranger while they are out is information they cannot
act on, delivered at the moment it will worry them most.

## ADR-023 — Sleep is protected, and YOLO does not override it

**Decision:** while the room is in sleep mode, the only room action Marvi may
take is switching a light off. Turning a light on, changing brightness, and
changing the mode are refused. The rule is enforced at the room boundary, so it
binds voice, the mind, vision, and YOLO identically.

**Reason:** every other guard in this system asks "did the user approve this?".
This one asks "is the user in a position to be asked?" — and someone asleep is
not. That makes it the first rule that must outrank YOLO, because YOLO is a
statement about prompting, not a statement about consent while unconscious.

The single exception exists because "never act" would be worse: a light left on
over someone asleep is precisely the situation an ambient assistant should fix,
and the worst case of switching it off is a dark room someone was already
sleeping in.

Live state is read before the guard decides, falling back to the last snapshot
if the sidecar is unreachable. A stale reading that says "awake" is the one
error that would let Marvi act during sleep, so the fallback fails toward
refusal.

## ADR-022 — Predecessor branding removed, functional paths kept

**Decision:** references to the predecessor assistant are removed from Marvi OS
prose, comments, and documentation. Generated lockfiles can still contain
third-party dependency identifiers that are not ours to rename.

**Reason:** Marvi OS is an independent product (ADR-001) and should not read
like a fork. The independent room sidecar now receives Marvi-owned paths through
`MARVI_PLUGIN_DATA` and keeps its runtime contract outside the Gateway core.
Provenance for adapted work is still recorded in
`docs/UPSTREAM.md` as `AGENTS.md` requires.

## ADR-019 — Two voices for two jobs

**Decision:** the full-duplex session keeps its LiveKit-owned streaming voice
path. Proactive announcements, Room welcomes, and Chat Read Aloud use kyutai
PocketTTS on the CPU and play through a standalone PortAudio output path. They
do not create, join, or depend on a LiveKit room.

**Reason:** the two jobs have opposite requirements. A session reply is a
first-token race that must be interruptible mid-sentence. A proactive sentence
is one short utterance Marvi chose to say, with nobody waiting and nothing to
barge into. Spending streaming GPU budget on the second is paying for a property
it does not need, on a machine where the 2 GB VRAM headroom is already
committed. PocketTTS measured 1.5 s to load and 0.811 RTF at 24 kHz on one CPU
thread.

Direct output means the always-on wake listener could hear Marvi. While PCM is
playing, Gateway writes a content-free, PID-bound marker and the wake daemon
pauses scoring. On Windows the marker owner is checked through a read-only
process handle—never the Unix `kill(pid, 0)` idiom, which terminates processes
on Windows. Stale or malformed markers are removed, so a crash cannot leave the
wake word disabled. Active full-duplex Voice is reported to Gateway and
downgrades proactive speech through the existing policy.

Speech failure degrades to the Island rather than losing the decision.

## ADR-020 — The Marvi Agent job bridge is dropped

**Decision:** Phase 7 no longer contains a durable job bridge to Marvi Agent for
coding, research, or long-running work. Phase 7 is the Windows update handoff
and the first release.

**Reason:** Marvi OS is an ambient voice and vision assistant. ADR-001 already
separates it from Marvi Agent precisely so the ambient lifecycle does not
inherit a coding agent's core and tool schema; adding a bridge back would
re-couple what that decision separated, and nothing in the shipped surface
depends on it. If delegation is wanted later it can arrive as its own phase with
its own evidence, rather than as a condition of shipping version one.

## ADR-018 — Letta evaluated as the mind, and not adopted

This settles ADR-014a. Measured against the `REAL-AGENCY.md` mind gates.

| Gate | Result |
|---|---|
| Native Windows without Docker/WSL2 | **fails as a service.** Letta's own docs say the Docker image "is no longer an actively maintained or supported Letta product surface", and the self-hosted server wants PostgreSQL with `pgvector`. A database server plus a vector extension is the same class of operational burden ADR-003 rejected. |
| OpenCode Go through a provider boundary | **fails as written, passes indirectly.** `openai.LLM.with_letta` takes only `agent_id`, `base_url`, `api_key` — the model is configured inside the Letta agent, so Marvi cannot pass its provider through. A self-hosted Letta *can* be pointed at an OpenAI-compatible endpoint, making it Marvi → Letta → OpenCode Go: two hops, with Letta owning the system prompt that `AGENTS.md` requires to stay small. |
| Memory across restarts, inspect/export/delete | **passes**, but the data lives in Letta's Postgres and leaves through Letta's API rather than a file the user owns. |
| Never treats account content as authority | **not provided.** Marvi's envelope boundary is still required either way. |
| Bounded background cost | **fails.** Letta's sleep-time agents make background model calls on their own schedule. The daily budget in `REAL-AGENCY.md` has to be enforced where the decision is made, and that would no longer be Marvi. |
| Foreground responsiveness | **unmeasured, structurally worse.** It adds a network hop in front of the provider on the path Phase 3 spent its effort shortening. No endpoint is configured on the target machine to measure. |
| A no-op decision is cheap | **fails.** The deterministic mind tick is a few SQLite reads; sleep-time agents are model calls. |

**The deeper finding is a role mismatch.** `with_letta` replaces the *foreground
conversational LLM*. The mind `REAL-AGENCY.md` describes is a *background,
event-driven decider*: journal, relevance, quiet hours, presence, cooldown,
budget, surface ceiling, and a decision record. Letta implements none of that —
its sleep-time agents consolidate Letta's own memory, they do not decide whether
interrupting a person is appropriate. Letta is therefore not an alternative to
the mind built in Phase 6; it is an alternative foreground LLM that happens to
bring its own memory.

**Decision:** the mind stays Gateway-owned. Letta is not adopted, and it is no
longer tracked as a memory or mind candidate. Reconsider it only as a foreground
LLM, and only if cloud-hosted conversation memory becomes something the product
wants — which today contradicts the local-first contract.

## ADR-017 — The browser is a tool, not an autonomous agent

**Decision:** browsing is a Playwright-backed session behind the same Gateway
policy as every other tool. Navigating, reading, listing links, and going back
are ungated; clicking, typing, and submitting are sensitive and confirmed.
Downloads and dialogs are refused outright rather than confirmed. The session
is off unless `MARVI_BROWSER` enables it, and every navigation passes the same
SSRF guard as `web_fetch`.

**Reason:** a page is the sharpest injection surface Marvi has, because the
agent both reads attacker-authored text *and* holds the controls on the same
surface. Enveloping page content stops the text from becoming instructions;
gating the controls stops a page from talking Marvi into pressing something.
Reading stays free so ordinary research is not a confirmation storm.

Playwright rather than an anti-detect stack such as Camoufox: the cached
Chromium is already on the machine, and evading bot detection is not a
behaviour this product should acquire by default.

**Deferred:** computer use, multi-tab sessions, and a browsing DSL. The agent
composes existing steps; a script language can wait until a real workflow
cannot be expressed without one.

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
bar (brand, page, window controls). The the predecessor assistant hidden-titlebar pattern is
adapted, not the native WCO overlay, because the Marvi OS brand chrome (mono
Collapse type, drag region, custom hover states) is the product surface.

**Reason:** A native title bar breaks the monochrome shell and cannot carry
the brand. The renderer-painted bar keeps one design system; window verbs stay
native via IPC (minimize/maximize/close handled in main with sender checks).

## ADR-015 — Local-only backdrop and chrome assets

**Decision:** Electric Gaze and all the predecessor assistant-adapted chrome ship as vendored
local assets or MIT npm dependencies. No runtime CDN fetch; source URLs and
licenses live in the UPSTREAM ledger.

**Reason:** The product contract is local-first and fail-closed. A backdrop
that needs the network violates the always-on promise and the UI contract.

## ADR-016 — Tag-driven releases with a repository-owned build script

**Decision:** Releases are cut only by `scripts/release.ps1`: bump `VERSION`,
both package mirrors, and the bootstrap crate; commit; create and locally
verify an SSH-signed annotated `v<semver>` tag; then push main and the tag. The
`Release` workflow gates the exact checkout build used by the updater and
publishes only `marvi-bootstrap.exe` plus `SHA256SUMS.txt`. Local packaging via
`scripts/build-desktop.ps1` never publishes, and electron-builder publishing
stays disabled so no unrelated build can create a release.

**Reason:** The Release channel selects the latest signed tag and builds that
checkout locally. The tag is therefore the product payload; signing and the
CI build gates prevent an untrusted or unbuildable checkout from becoming an
update. `workflow_dispatch` builds are dry runs: artifacts upload, no GitHub
Release is created.

## ADR-017 — Tauri bootstrap replaces the PowerShell updater

**Decision:** The PowerShell update handoff (`scripts/desktop-update/windows.ps1`)
is replaced by a small Tauri binary, `marvi-bootstrap.exe` (`apps/updater`),
that serves as both the installer and the updater. It is a thin GUI shell over
a headless Rust core (`marvi-bootstrap-core`) that does the git orchestration.
The Electron app spawns it on update and reads its result marker unchanged.

**Reason:** A frozen PowerShell script could not be signed or shrink the
installer, and its in-place `git reset --hard` rollback could not preserve a
half-written build. The bootstrap keeps the repository-owned handoff model
(the checkout updates itself) while fixing the safety gaps found in review:
read-only check path, channel model (`release` default vs opt-in `nightly`),
liveness-aware in-progress marker, build-output snapshot/restore, and release
tag integrity verification. The binary is named `marvi-bootstrap` (not
`marvi-updater`/`installer`) so Windows installer-detection heuristics never
auto-elevate it.

**Consequence:** The bootstrap binary and checksum are the only repository-built
GitHub Release assets. A fresh install clones the signed tag, builds, and
atomically swaps it into place; updates follow the same tag with rollback.

## ADR-024 — Account authority stays in Gateway; credentials stay in Composio

**Decision:** Marvi uses the official Composio SDK and hosted Connect Links for
provider OAuth. Gateway owns the project-key setup, connection lifecycle,
per-toolkit read/write/admin ceiling, dynamic tool broker, provider sync state,
and trigger-to-ARC boundary. Provider OAuth tokens remain in Composio. The LLM
receives two stable discovery/execution tools instead of the full remote
catalog; every execution re-resolves its schema and capability class.

Gmail, Google Calendar, Slack, Notion, GitHub, and Google Drive have native
memory providers with independent per-connection cursors and health. Realtime
subscriptions and optional signed webhooks enter the same deduplicated,
untrusted journal/memory path. Typed Chat and LiveKit Voice consume the same
Gateway-published raw JSON schemas and never call Composio directly.

**Reason:** OAuth lifecycle, remote schemas, and event transport already exist
upstream, while user authority, confirmation, audit, provenance, and durable
memory are Marvi product policy. Keeping that seam in Gateway prevents React,
voice workers, or external content from becoming a second execution authority.

## ADR-025 — ARC cognition is auxiliary and observability is content-free

**Decision:** Every LLM call made for ARC's mind, presence judgement, memory
reflection, or subconscious schedule declares `job="aux"` and a named Models →
Auxiliary role. A configured role pins its provider/model; Auto uses the active
provider's `default_aux_model`. Deterministic ingest, recall, graph projection,
and consolidation remain model-free. Provider, scheduler, mind, memory, and
account boundaries log correlation IDs, routes, models, timing, usage, counts,
fallbacks, and outcomes, but never prompts, completions, memory bodies, or
external payloads.

**Reason:** Background cognition must not silently consume the expensive main
conversation model, and future failures must be traceable across scheduler,
policy, memory, and provider boundaries. Content-free structured metadata gives
that evidence without turning diagnostic files into a second memory database.

## ADR-026 — Durable memory is one provider, selected at the Gateway

**Decision:** Gateway exposes a five-method `MemoryProvider` seam and selects
exactly one of the local SQLite store, Mem0, or Honcho. Provider-owned semantic
retrieval stays below that seam. The local ARC reflection/dreamer is disabled
when an external provider owns consolidation. `USER.md` remains authoritative
over Honcho's derived peer card. Mem0 is pinned to 1.0.11; upgrading to its
ADD-only 2.x algorithm requires passing the correction acceptance case first.

**Reason:** Running stores in parallel recreates conflicting truth with no
authority marker. Honcho and Mem0 already own extraction/retrieval, while
Marvi's product-specific responsibility is provider choice, untrusted-content
containment, UI configuration, audit, and foreground-safe degradation.

## ADR-027 — Connectors are direct-only, and Capabilities is their home

Refines ADR-024, which left the credential model open.

**Decision:** Marvi talks to Composio directly with the user's own project
key. No Marvi-hosted broker, no BYO-versus-hosted mode switch, and no
provider-neutral backend seam with a second implementation behind it. Skills,
Connectors, MCP and third-party plugins move to a Capabilities section in the
main sidebar; Settings keeps Marvi's own plugins.

Three supporting rules:

- **Identity is per installation.** A generated entity id, not the literal
  `"default"`, which addresses one Composio identity from every install.
- **Effects come from a catalog, not from words.** A curated per-toolkit
  catalog is authoritative, and an uncurated action on a catalogued toolkit is
  refused rather than guessed. The word heuristic survives only where no
  catalog exists, and an unknown verb still fails closed to `admin`.
- **Disconnecting retracts what was ingested.** Revoking a connection removes
  the memories it produced, counted before the deletion rather than after.

**Reason:** The broker question was the one thing blocking a design that was
otherwise agreed. It is only a question for a product with more than one user;
Marvi has one, who holds his own key. Answering it "never" removes an entire
axis of design — custody, billing, multi-tenancy, a seam with two
implementations — at no cost to anything shipping.

The three supporting rules are not new caution. Each is a defect found in
Marvi's own code while reviewing this: a shared identity literal, a classifier
that read `GET` in a slug as proof an action was read-only, and a disconnect
that revoked upstream while leaving the ingested content recallable. openhuman
reached the same conclusions with the same seam and, on the classifier, in the
same way — by a review catching it rather than a test.

**Not decided here:** remote MCP transports. Marvi's bridge is stdio-only, so
the registry listing drops hosted-only entries rather than offering something
that cannot launch. Supporting streamable-http would change that and is its
own decision.
