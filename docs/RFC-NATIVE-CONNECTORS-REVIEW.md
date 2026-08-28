# Review — RFC-NATIVE-CONNECTORS

Reviewed against Marvi's shipping code (`services/gateway/src/marvi_gateway/accounts.py`,
`account_triggers.py`, `ingest.py`) and against `D:\openhuman`, which has been
running the architecture this RFC proposes for long enough to have found its
edges.

## Verdict

The recommendation is right, and it is no longer a bet. Native Marvi
experience + Composio as a replaceable engine + a narrow Gateway seam is the
same architecture openhuman independently arrived at and shipped: backend or
direct Composio routing behind one domain, per-toolkit read/write/admin scope
gating owned locally, curated catalogs, and a provider registry the core talks
to instead of talking to Composio. Two projects converging on the same shape
from different languages and different runtimes is stronger evidence than
anything Gate 1 would produce.

What the RFC gets wrong is the balance. It treats five things as open questions
that openhuman has already answered in production, and it does not mention four
things openhuman found the hard way that Marvi does not have. The open
questions are cheaper than the RFC thinks; the gaps are more expensive.

## Five questions openhuman already answers

### 1. One-click versus BYO key — the answer is "both, selected by a mode"

The RFC treats this as a fork (Gate 2, Product Q1/Q2) that has to be resolved
before the seam can be designed. openhuman does not resolve it. It ships both:

- **backend mode** — their broker owns the Composio API key, billing, the
  toolkit allowlist, HMAC webhook verification and trigger fan-out; the core
  never touches the Composio API.
- **direct mode** — `composio.mode = "direct"`, gated on a user-supplied key in
  the encrypted keychain, talking to Composio v3 against the user's own tenant.

`composio.get_mode` reports whether a key is set and never returns it;
`set_api_key`/`clear_api_key` never log or return it — the same contract as
Marvi's `ask_secret`.

This unblocks the RFC. The mode is a field in the seam from day one. BYO is
what ships now, because Marvi is one user with their own key. A broker is a
later flip that changes no call site. Nothing else in the design waits on it.

### 2. Per-installation identity — a config value

Immediate finding 1 is real: `DEFAULT_USER_ID = "default"` (`accounts.py:21`)
is a shared identity. openhuman threads `config.composio.entity_id` through
every authorize and execute call. This is a config value with a
per-installation default, not a redesign, and it should not be sitting behind
five gates.

### 3. Action effects inferred from words — openhuman hit this exact hole

This is the most valuable thing in the comparison. openhuman has the same verb
heuristic Marvi has (`classify_unknown`), and a code review (PR #4702) found
that it cannot be trusted. Their resolution, in
`integrations/composio/catalog.rs`:

> A toolkit that HAS a curated catalog: the slug's scope is authoritative ONLY
> if the slug is one of that catalog's curated entries. An uncurated slug on a
> cataloged toolkit resolves to `None` — it must NOT fall through to the verb
> heuristic, which can misclassify an uncurated write action as `Read` by name
> alone.

Marvi's `classify_action` is *better than theirs on the unknown-verb case* — an
unfamiliar verb returns `"admin"` (`accounts.py:152`), failing closed, with a
comment saying exactly why. But it fails **open** on the known-but-wrong verb,
which is the case that bites: any action slug containing `GET`, `LIST`, `CHECK`
or `STATUS` is classified `read` and executes without confirmation, whatever it
actually does upstream.

The fix is openhuman's: a curated per-toolkit catalog is the trust anchor, and
an uncurated slug on a cataloged toolkit is refused rather than guessed. The
heuristic survives only for toolkits with no catalog at all.

That also answers Architecture Q6 — the reviewed effect overlay lives beside
the scope preferences, as data, keyed by slug, with the catalog as authority.

### 4. The scope model is settled

Both projects converged on per-toolkit read/write/admin, stored locally,
enforced before the provider call, defaulting to read+write without admin.
openhuman additionally documents that the *read* of a scope preference fails
open (a KV error is not evidence the user revoked anything) while the *write*
does not. Marvi should copy that asymmetry when the preference store grows a
failure mode.

### 5. Connect-flow mechanics the RFC never mentions

Composio has no deep-link callback, and in direct mode the v3 link endpoint
returns no stable connection id — so confirming a connection is poll-based by
necessity. openhuman's flow, worth copying verbatim:

- poll from 1.5s, ×1.5 backoff to a 4s cap, 5-minute timeout;
- a window-focus / tab-visible handler pokes an immediate re-poll and resets the
  cadence to fast, because the user switching back from the browser is a
  near-perfect "just finished authorizing" signal;
- provider-specific required fields (Jira subdomain, WhatsApp WABA id, Dynamics
  org name) in a declarative registry rather than per-toolkit booleans;
- a `needs-fields` recovery phase for Composio error 612 that re-collects those
  fields and retries, instead of surfacing a raw backend error.

Marvi will hit every one of these the first week Connectors ships.

## Four gaps the RFC does not name

### 1. Disconnect does not retract what was ingested

`ComposioAccounts.delete` revokes at Composio and invalidates the connection
cache. Nothing touches memory. openhuman's `delete_connection` takes
source-scoped memory-cleanup targets and has a whole `ops/memory_cleanup.rs`
behind it.

This matters more for Marvi than for openhuman. Marvi's memory graph *is* the
retrieval substrate, and `AccountTriggerIngest` writes external content into it
continuously. Disconnecting Gmail today leaves every ingested email in the
graph — still recalled, still spoken, with no live connection left to correct
or refresh it. The user's mental model of "disconnect" will not match that.

The ledger to do it already exists: `ingest.py` keys seen rows on
`(toolkit, connection_id, provider_id)`. The retraction is buildable now; it is
simply not wired to `delete`. I would treat this as a prerequisite for the
Connectors UI rather than a follow-up, because the UI is what makes disconnect
a one-click action.

### 2. No error classification at the seam

Marvi has five exception types (unavailable / auth / scope / rate-limited /
transient), which is a good start. openhuman found (issue #1797) that without a
classifier every tool failure buckets as a generic gateway 502, and added
`ComposioErrorClass` plus a formatter so the *model* receives a stable,
actionable failure string rather than a stack trace shape.

That is the answer to Testing Q3, "how are ambiguous timeouts reported", and it
belongs in the seam contract, not in the implementation behind it.

### 3. The post-OAuth propagation race

`auth_retry.rs` is a single-shot retry for the "Connection error, try to
authenticate" window right after a connection is created — the token has not
propagated yet and the first call fails. Real, reproducible, and it lands
exactly on the first action a user tries after connecting, which is the worst
possible place for it. Not mentioned in the RFC.

### 4. No trigger archive

openhuman keeps a JSONL trigger-event archive partitioned by UTC day, exposed
as `list_trigger_history`. Marvi's triggers ingest into memory and the journal
and keep no raw record, so "why does Marvi believe this" about a
trigger-created memory is unanswerable after the fact. Given how much of this
project's debugging has been reading back what actually arrived, that archive
would have paid for itself already. It also answers the retention half of the
RFC's trigger-guarantees question without asking Composio anything.

## On the Capabilities section

Your split — Capabilities in the sidebar (Skills, Connectors, Plugins, MCP),
Settings › Plugins for Marvi's own like Smart Room — is better than the RFC's
"plugins sit above connectors" framing, because it separates *what Marvi can
reach* from *what Marvi is*. Two design notes from openhuman:

**Four tabs, one shape.** Their MCP tab is a single table with filter chips
(All / Installed / Registry) — one search box, installed and available servers
in the same list separated by a status badge, not two views the user has to
switch between. Skills and Connectors want exactly that shape: Marvi already
has a Composio toolkit catalog and a skills store catalogue behind it. Four
tabs that behave identically is the whole design, and it means one component.

**Ship the metadata, fetch only the status.** openhuman keeps a frozen local
catalog of 119 toolkits — names, categories, descriptions, logo URLs,
permission labels — and lets the live backend decide only what is *available*.
That is why their grid paints instantly. It is also the structural answer to
the class of bug you hit on Skills: a page whose first paint depends on a
network fan-out has no good failure mode, and "loading forever" is what it looks
like when one fetch hangs.

## On the gates

Gates 3–5 (seam design, curated behavior, plugin model) are the actual work and
are in the right order. Gate 1 and most of the Composio due-diligence list are a
procurement process for a project with one user and their own API key —
retention rules, incident commitments, regional processing and deletion
guarantees are questions for a company signing a contract, and answering them
now costs weeks and changes nothing you would do.

Three of them do change a decision and should be kept:

- **version pinning and a changelog** — Immediate finding 2 is real; an action
  whose schema moves under you is the failure mode with no local symptom.
- **idempotency for writes** — an ambiguous timeout on a send is the one error
  that cannot be retried safely, and the answer determines the seam's result
  type.
- **desktop credential extraction** — only if a broker ever ships; under BYO the
  key is the user's own and the threat model is the one Marvi already has for
  provider keys.

The rest defer until there is a second user. That is not a shortcut: the seam is
what makes deferring safe, and the seam is Gate 3.

## On the graph

You said openhuman's is the exact design you want. It is the same stack Marvi
already runs — Pixi + d3-force over a render-agnostic layout module shared by
every renderer — and on labels Marvi's is ahead: openhuman's labels are
always-on with no zoom fade and no decluttering, which is precisely the "total
mess when zooming" you reported and which Marvi's `textFade` + degree-ordered
declutter already fixes. Three things of theirs are worth taking:

- **`ZOOM_MIN = 0.05`, one shared floor for auto-fit and wheel.** Marvi is at
  `0.18`. Their comment records both failures: a higher floor clamps the
  auto-fit above the scale needed to show every node, so large graphs render
  "too zoomed in" with the outer nodes off-screen; and a *separate* lower
  auto-fit floor produces a zoom-snap where the first wheel tick jumps back up
  to the manual floor. Marvi will hit the first as the store grows.
- **An SVG fallback sharing the layout module**, used where WebGL is absent
  (jsdom). It makes the graph testable for real instead of mocking Pixi.
- **Reveal after the simulation settles** rather than showing it jitter into
  place.

Their hard cap on node radius exists because a synthetic merge level multiplied
into thousands of pixels and blew up `forceCollide`. Marvi's `√degree` growth
cannot do that, so no change is needed there.

## Order I would do it in

1. `entity_id` from config — one value, unblocks per-installation identity.
2. Curated catalog as the effect authority; uncurated-on-cataloged fails closed.
3. Disconnect retracts ingested memory, using the existing ingest ledger.
4. The seam, with `mode: byo | broker` in it from the start.
5. Capabilities UI — four tabs, one shape, local metadata, live status only.
6. MCP last: it is the only one with no existing Marvi surface to preserve.
