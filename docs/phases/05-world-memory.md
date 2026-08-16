# Phase 5 — World Context and Memory

**Status:** complete
**Depends on:** Phase 4 policy/audit path

## Scope

- Official Composio SDK for supported account OAuth and tools.
- Email, LinkedIn, X, and other connected context retrieved on demand.
- External writes pass through Confirm/YOLO and idempotent audit boundaries.
- Select a maintained memory foundation after a focused bakeoff; add episodic,
  semantic, forget, and export flows.

## Acceptance evidence required

- External content remains untrusted data and never becomes system instruction.
- Sandbox read/write, revoked OAuth, reconnect, duplicate-write, and memory
  deletion/export tests.

## Implemented

- `marvi_gateway.untrusted`: a nonce-delimited provenance envelope for every
  piece of external content, with a size cap and injection-signal reporting for
  the audit. See ADR-015 for why containment is structural rather than lexical.
- External-write idempotency in the tool router. Tools declare `external=True`;
  the router computes or accepts an idempotency key, checks it *before* asking
  for confirmation, and returns the recorded result instead of acting twice.
  A failed write is never recorded as done.
- `marvi_gateway.accounts`: a thin adapter over the official Composio SDK.
  Reads are enveloped, writes are sensitive and external, dead connections are
  refused before any network call, and SDK/HTTP failures are normalised into
  four typed errors.
- `marvi_gateway.memory`: local SQLite + FTS5 episodic and semantic memory with
  `remember`, `search`, `recent`, `forget`, `forget_matching`, `forget_all`,
  `export`, and a model-free `world_summary`. Untrusted-origin memories are
  re-enveloped on recall.
- Accounts and Memory control-center pages, an `accounts` runtime component, and
  a Memory page with an explicit two-step "forget everything".
- Voice tools gained `recall` and `remember`; the agent prompt now carries the
  standing rule that `[EXTERNAL DATA ...]` content is reported, never obeyed.

## Evidence

Live against the user's real Composio account (composio 0.19.0) through a real
`uvicorn` Gateway process.

| Gate | Result |
|---|---|
| Connected-account inventory | 9 raw connections collapsed to 7 toolkits: 4 connected, 3 need reconnect |
| Live Gmail read | `executed`, 8,185 bytes, enveloped, exactly one end marker, content inside |
| Live Calendar read | `executed`, 4,876 bytes, enveloped, one end marker |
| Revoked OAuth (live) | `slack`/`reddit` refused before any network call; `notion` refused as not connected |
| Reconnect | a toolkit flipping back to `ACTIVE` starts working with no Gateway restart |
| Envelope escape | six attack shapes, including a literal `[END EXTERNAL DATA]`, all stayed inside |
| Injection through memory | stored untrusted, re-enveloped on recall, nothing escaped either hop |
| Injection signals | `override`, `persona`, `role-inject`, `exfiltration` all flagged; content preserved verbatim |
| Duplicate write | second identical send deduplicated, provider called once, no second confirmation |
| Failed write | not recorded as done; the retry executes |
| Memory delete/export | `forget`, `forget_matching`, `forget_all`, and verbatim `export` all verified |

Memory bakeoff measurements over 10,000 entries: 12.94 ms median search
(22.11 ms worst), 4.07 ms per write, 1.90 MiB on disk, 1.15 ms reopen with all
10,000 surviving, 30 ms full export, zero VRAM, zero new dependencies. The
per-write cost is one commit per write; it is well within assistant write rates
and is not batched on purpose.

Automated coverage: 111 Python tests (18 boundary, 9 idempotency, 18 accounts,
13 memory) and 22 desktop tests.

## Closed gates

- **Real outbound write.** One `send_email` ran the full path — confirmation
  token, exact-argument approval, audit, idempotency — and Gmail returned
  message id `1a008f2f91cc7f2f`. The immediate duplicate was deduplicated and
  the provider was called once. The requested `noreplay.coregram@gmail.com`
  sender could not be used: it is not a connected account and has no verified
  send-as alias, so the only authorised identity was used instead.
- **Account event ingestion.** `marvi_gateway.ingest` polls connected accounts
  on a bounded tick, normalises Gmail and Calendar items, and deduplicates by
  provider id. Live: 20 real items ingested, second poll ingested 0 and skipped
  20, building 18 graph entities from real senders. A provider outage is a
  logged no-op, and one dead provider does not stop the others.
- **Memory depth.** Knowledge graph, reflection, consolidation, and
  reinforcement — see the memory section below.

## Memory: episodic, semantic, graph, reflection, consolidation

- **Graph.** Entities and relations with `ON DELETE CASCADE`, traversable in
  both directions, case-insensitive, and collapsing restated facts rather than
  growing. Edges from untrusted content stay untrusted.
- **Reinforcement.** Recall bumps `strength` and `last_used`, so consolidation
  can tell a useful memory from noise without anyone tuning a policy.
- **Reflection.** Subjects repeated `PROMOTE_AFTER_REPEATS` times become
  semantic facts. Idempotent, and a pass with nothing to do is free. The
  `summarise` seam accepts an LLM pass without touching storage.
- **Consolidation (the sleep pass).** Episodic entries older than
  `EPISODIC_TTL_DAYS` that were never reinforced are dropped; semantic facts
  and anything ever recalled are never dropped. Orphaned entities are tidied.

## Tool surface (ADR-016)

24 tools registered live, 10 sensitive. Room (4), accounts (4), memory (6),
web (3), file (4), terminal (1), process (2), plus any MCP tools discovered
from configuration under `mcp__<server>__<tool>`.

| Gate | Result |
|---|---|
| SSRF guard | loopback, private, link-local, and non-http refused after DNS resolution; blocked `127.0.0.1:17842` and `169.254.169.254` live |
| Workspace containment | `..`, absolute paths, and root deletion refused; refuses entirely without `MARVI_WORKSPACE_ROOT` |
| Tool output | web pages, file contents, command output, and MCP results all enveloped |
| MCP policy | sensitive unless the tool declares a read-only hint; undeclared arguments refused by schema mapping |
| Live web search | Brave returned real results through the router, enveloped, hostile snippets flagged |

## Still open

- LinkedIn is still **not** connected on the Composio account despite being
  added — the live listing shows the same 9 connections with no `linkedin`. X
  is out of scope by request.
- Letta remains a candidate for the mind rather than the store; see ADR-014a.
