# RFC — Marvi Connectors: native product surface over a maintained integration platform

**Status:** draft for investigation; no implementation decision

**Date:** 2026-08-28

**Owner:** Marvi OS

**Relates to:** ADR-007, ADR-016, ADR-024, Phase 5, Accounts, ARC ingestion

## Summary

Marvi should offer a Claude-like Connectors and Plugins experience: a user
finds Gmail, Google Calendar, Google Drive, GitHub, Spotify, and other services
inside Accounts, connects an account with a simple browser authorization flow,
and immediately gives Marvi well-described tools and context for that service.

The original proposal was to make these integrations fully native to Marvi so
that built-in providers would not depend on MCP, Composio, another hosted
service, Docker, or an independently administered integration platform. The
research found no mature upstream that provides all of the following as a
small, embeddable, permissively licensed desktop library:

- a broad maintained provider catalog;
- managed OAuth applications and token refresh;
- tested action implementations and schemas;
- triggers, retries, rate-limit handling, and provider edge cases;
- agent-oriented tool descriptions and behavior guidance;
- native-Windows, in-process operation with no separate control plane; and
- a right to redistribute the result as a core capability of Marvi OS.

The current leading direction is therefore not “write every connector” and not
“replace Composio with another integration server.” It is to keep Composio as
the maintained connector engine while making the product surface, policy,
memory, audit, and agent behavior entirely Marvi-owned. A provider-neutral
Gateway seam would prevent Composio from becoming an irreversible dependency
and would allow selected native connectors later when evidence justifies their
maintenance cost.

This RFC records the problem, the two rounds of discussion, the repository
audit, external research, proposed architecture, unresolved constraints, and
the questions that must be answered before this becomes a plan or ADR.

## Why this is an RFC rather than a decision

ADR-024 currently says that account authority stays in Gateway while provider
credentials stay in Composio. That remains the accepted implementation.

This RFC does not supersede ADR-024 and does not authorize a connector rewrite.
It exists so the idea can be investigated without advertising research as a
shipped capability. If the proposal is accepted, a later ADR must define the
selected backend, credential boundary, distribution model, provider rollout,
and migration from the existing `ComposioAccounts` implementation.

## Discussion history

### First request: make connectors genuinely native

The initial request was to review Accounts and its pipeline and investigate a
Claude-like Connectors and Plugins capability. The desired experience included
Google tools, Gmail, Calendar, Spotify, GitHub, Uber Eats, and similar services.
The motivation was to avoid accessing these services through MCP or Composio
and instead make the capability part of Marvi itself.

Several upstream candidates had already been identified, including Zapier,
Metorial, and OpenConnector. The central requirement was that the result should
not be a third-party hosted product or a Docker service that users must operate.

### First response: separate product-native from implementation-native

The first conclusion distinguished two meanings of “native”:

1. **Product-native:** Marvi owns discovery, Accounts UX, connection state,
   tool routing, confirmation, audit, memory, citations, and failure behavior.
2. **Implementation-native:** Marvi also owns OAuth credentials and calls every
   provider API directly through code maintained in this repository.

The research initially recommended a hybrid architecture:

- create a provider-neutral `ConnectorHub` in Marvi Gateway;
- implement strategic providers directly against official APIs;
- use the existing PKCE broker and Windows DPAPI token store;
- treat OpenConnector as an upstream reference or focused code donor;
- keep Composio as an optional long-tail and hosted-trigger fallback; and
- use MCP only as a compatibility path for custom connectors, not for built-in
  providers.

That proposal maximized local ownership, but it still left Marvi responsible
for action code, tests, API changes, provider-specific semantics, and ongoing
maintenance for every native connector.

### Second request: account for the real maintenance burden

The follow-up correctly rejected treating a connector as “just some HTTP
calls.” A production connector is code plus:

- OAuth and scope behavior;
- tests and provider sandboxes;
- action schemas and descriptions;
- error and reconnect behavior;
- pagination, rate limits, and retries;
- idempotency and ambiguous-write handling;
- triggers and polling;
- context and workflow guidance;
- provider API churn;
- bugs, edge cases, and long-term support.

The revised question was whether a ready connector SDK or catalog can remove
that burden and whether Composio is therefore the correct upstream.

### Second response: Composio is probably the pragmatic upstream

The revised conclusion was that there is no “maintenance-free, broad,
fully-local connector SDK” matching Marvi's constraints. Composio is likely the
correct connector engine for the current product because it already supplies
the parts Marvi does not want to maintain:

- provider OAuth differences and managed OAuth applications;
- credential storage, refresh, reconnect, and revocation;
- provider action implementations and evolving schemas;
- rate-limit and API error handling;
- triggers and webhook infrastructure; and
- a broad long-tail catalog.

Marvi can still make this a native product capability. Users would see Marvi
Connectors, not MCP servers, Composio action slugs, or an external integration
dashboard. Composio would be an implementation dependency behind a narrow
Gateway seam.

## Terminology learned from Claude

Anthropic's current product separates three concepts:

- A **connector** gives the model permissioned, live access to a service's data
  and actions.
- A **skill** teaches repeatable behavior and workflows. It may contain
  instructions, references, templates, and scripts.
- A **plugin** packages skills, connectors, commands, hooks, and/or sub-agents
  for a role or workflow.

Claude connectors commonly use MCP as their transport, but MCP is not what
makes the experience a connector. The important properties are discoverability,
authentication, permissions, useful tool behavior, and integration with the
host application's safety and UX.

Marvi can adopt the same conceptual model without exposing MCP internally:

| Claude concept | Proposed Marvi concept |
| --- | --- |
| Connector | Gateway-owned connected-service capability |
| Skill | Marvi workflow/instruction bundle |
| Plugin | Installable bundle declaring skills, connector requirements, and scoped behavior |
| MCP connector | Optional adapter for custom or externally supplied tools |

Primary sources:

- [Anthropic: use connectors to extend Claude](https://support.claude.com/en/articles/11176164-use-connectors-to-extend-claude-s-capabilities)
- [Anthropic: use plugins in Claude](https://support.claude.com/en/articles/13837440-use-plugins-in-claude)
- [Anthropic official plugin directory and package structure](https://github.com/anthropics/claude-plugins-official)
- [Anthropic Google Workspace connector capabilities](https://support.claude.com/en/articles/10166901-use-google-workspace-connectors)
- [Model Context Protocol](https://modelcontextprotocol.io/)

## Current Marvi Accounts pipeline

Marvi already owns considerably more than an MCP client. The current route is:

```text
Accounts renderer
    -> narrow Electron IPC
    -> Gateway /accounts and /tools routes
    -> ComposioAccounts
    -> official Composio SDK and hosted account service
    -> provider API
```

### Responsibilities Marvi already owns

- Accounts catalog, lifecycle, scope, sync, and health presentation.
- A read/write/admin ceiling per toolkit.
- Stable `account_tool_search` and `account_tool_execute` broker tools.
- Confirm/YOLO, exact-argument confirmation, audit, and idempotency.
- Structural containment of untrusted external content.
- Gmail, Calendar, Slack, Notion, GitHub, and Drive normalization.
- Per-connection cursor, fingerprint, last success/error, and item counts.
- ARC journal and durable-memory ingestion.
- Trigger identity checks, deduplication, and untrusted envelopes.

### Responsibilities Composio currently owns

- Provider catalog metadata.
- Hosted OAuth and provider credentials.
- Connected-account state and refresh.
- Raw action schemas and action execution.
- Trigger subscription and signed-webhook parsing.
- Provider API compatibility and much of its operational edge handling.

### Relevant implementation

- `services/gateway/src/marvi_gateway/accounts.py`
- `services/gateway/src/marvi_gateway/ingest.py`
- `services/gateway/src/marvi_gateway/account_triggers.py`
- `services/gateway/tests/test_accounts.py`
- `services/gateway/tests/test_account_platform.py`
- `apps/desktop/src/renderer/src/App.tsx` (`AccountsPanel`)
- `apps/desktop/src/main/index.ts` (Accounts IPC)
- `docs/ARCHITECTURE.md` (`Accounts and world context`)
- `docs/phases/05-world-memory.md`
- `docs/DECISIONS.md` (ADR-024)

## Immediate findings in the existing Composio path

These findings are independent of whether this RFC is accepted.

### Shared `default` Composio identity

`accounts.py` currently sets `DEFAULT_USER_ID = "default"`. Composio's own
authentication guidance says not to use `default` in production because
connections are stored under that user identifier. Reusing one project key on
multiple Marvi installations could cause those installations to address the
same Composio identity.

The production identity should be a stable Marvi user or installation UUID,
with an explicit migration for existing connections.

Source: [Composio authentication model](https://github.com/ComposioHQ/composio/blob/next/docs/content/docs/authentication/index.mdx).

### Unpinned action versions

Manual execution currently requests
`dangerously_skip_version_check=True`. Composio deliberately requires explicit
toolkit versions so schema changes do not silently alter production behavior.
Marvi should pin or explicitly approve toolkit version changes, retain the
safe unknown-action classification, and rerun protocol-shaped and live sandbox
tests before advancing versions.

Source: [Composio tool version behavior](https://docs.composio.dev/reference/sdk-reference/typescript/tools).

### Action effects inferred from words

The current broker conservatively classifies action slugs by words such as
`GET`, `SEND`, `UPDATE`, and `DELETE`. Unknown actions become `admin`, which is
safe, but name-based classification is not a complete behavioral contract.

Popular actions should have a reviewed overlay declaring:

- read, write, destructive, permission-changing, or externally visible effect;
- provider scopes;
- idempotency support;
- whether an ambiguous result is safe to retry; and
- source/citation behavior.

This overlay is much smaller than maintaining the connector implementation and
is legitimate Marvi product policy.

## Requirements

### Product requirements

1. Accounts presents a searchable Marvi connector directory.
2. A user connects a supported account through an understandable authorization
   flow and can reconnect, disable, or revoke it.
3. Marvi automatically considers a connected capability when relevant without
   placing the entire catalog in every voice prompt.
4. Reads return useful source identity and canonical provider links.
5. Writes inherit Confirm/YOLO, validation, audit, and idempotency.
6. Multiple accounts for one provider are explicit; the model never guesses.
7. External content always enters the untrusted boundary.
8. Connector failure is isolated and visible without taking down voice,
   memory, or unrelated connectors.
9. Background sync is bounded and does not depend on renderer visibility.
10. Plugins may require connectors but may not contain or retrieve credentials.

### Maintenance requirements

1. Marvi should not implement a broad connector catalog from scratch.
2. Provider API and OAuth changes should be absorbed primarily by a maintained
   upstream.
3. Upstream schemas and action changes must be versioned or canaried.
4. High-value actions need real provider sandbox tests, not only mocks.
5. The upstream license and commercial redistribution rights must be clear.
6. A connector backend must be replaceable without rewriting Accounts, ARC,
   confirmation, or audit.

### Deployment requirements

1. Raw microphone and camera remain local and unrelated to connector traffic.
2. No Docker or WSL2 requirement may be introduced for Accounts.
3. No independent connector dashboard should become a required product surface.
4. The renderer never receives project secrets, OAuth refresh tokens, or
   provider tokens.
5. Any hosted dependency must be explicitly disclosed in UI and diagnostics.

## Non-goals

- Recreating Zapier-style user-authored workflow automation.
- Loading every remote action schema into the LiveKit voice agent.
- Treating a skill file as trusted executable authority.
- Promising every catalog provider has equal quality or realtime behavior.
- Hiding Composio from technical logs, diagnostics, licensing, or privacy
  documentation.
- Claiming that Composio-backed connectors work offline.
- Building consumer Uber Eats ordering against merchant-only APIs.

## Options researched

### Option A — direct official provider APIs

Marvi would register OAuth applications, store provider tokens with Windows
DPAPI, and call official APIs or SDKs from Gateway.

**Strengths**

- Maximum local privacy and control.
- No remote integration intermediary.
- Exact Marvi-oriented schemas and semantics.
- No additional runtime or control plane.

**Weaknesses**

- Marvi owns every connector's code, tests, bugs, scopes, behavior, and churn.
- Provider verification and approval remain necessary.
- Local-only deployments cannot receive many provider webhooks without a
  publicly reachable service.
- The catalog grows linearly with permanent maintenance responsibility.

**Use if:** a strategic provider has a measured privacy, latency, reliability,
cost, or capability problem that Composio cannot satisfy.

Provider constraints found during research:

- Google supports browser authorization with desktop loopback callbacks, but
  Gmail sensitive/restricted scopes require verification and may require
  continuing security review:
  [desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app),
  [verification requirements](https://support.google.com/cloud/answer/13464321).
- GitHub recommends GitHub Apps over broad OAuth apps because GitHub Apps have
  fine-grained permissions and short-lived tokens:
  [GitHub OAuth application best practices](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/best-practices-for-creating-an-oauth-app).
- Spotify recommends Authorization Code with PKCE for desktop/public clients
  and imposes development-mode limits:
  [authorization](https://developer.spotify.com/documentation/web-api/concepts/authorization),
  [redirect URI requirements](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri).
- Uber Eats Marketplace APIs are for merchants, POS systems, menu management,
  and order fulfillment; production scopes require approval. They do not
  provide a general consumer “order food for me” connector:
  [overview](https://developer.uber.com/docs/eats/introduction),
  [authentication](https://developer.uber.com/docs/eats/guides/authentication).

### Option B — Composio

Composio supplies managed authentication, connected accounts, toolkits,
versioned actions, execution, and triggers through its hosted service and
official SDK.

**Strengths**

- Already integrated and tested in Marvi.
- Broad catalog with one SDK contract.
- Managed OAuth avoids building every provider flow.
- Action definitions, execution, refresh, and triggers are maintained upstream.
- Marvi already owns the important policy and memory boundary around it.

**Weaknesses**

- Provider credentials and action execution depend on a hosted third party.
- Availability, pricing, rate limits, schema quality, and provider coverage are
  external dependencies.
- Realtime and polling behavior can differ by provider.
- A polished one-click consumer experience creates a project-secret
  distribution problem for a local desktop application.

Sources:

- [Composio documentation](https://docs.composio.dev/docs)
- [Managed authentication](https://docs.composio.dev/toolkits/managed-auth)
- [Auth configs and token ownership](https://docs.composio.dev/reference/v3/api-reference/auth-configs)
- [Tools and execution](https://docs.composio.dev/kb/topic/tools-actions-and-execution)
- [Triggers](https://docs.composio.dev/docs/triggers)
- [Composio SDK repository](https://github.com/ComposioHQ/composio)

**Current assessment:** best fit if the goal is to skip broad connector
maintenance. Retain behind a provider-neutral Marvi seam.

### Option C — OpenConnector

OpenConnector is an Apache-2.0 connector gateway with OAuth, SQLite or
PostgreSQL storage, provider definitions, action schemas, policies, and local
executors. It can run as Node.js without Docker.

**Strengths**

- Permissive repository license.
- Inspectable provider definitions, scopes, and executor code.
- Local Node + SQLite is possible.
- Gmail, GitHub, and Spotify have concrete provider directories.
- Explicitly distinguishes locally executable actions from catalog-only
  metadata.

**Weaknesses**

- It is another Gateway/control plane, not a small connector library.
- Embedding it duplicates Marvi connection identity, OAuth storage, policy,
  logs, administration, lifecycle, and action routing.
- A separate Node service contradicts the desire for one Gateway-owned account
  authority even if Docker is avoided.
- “1,000+ providers” does not mean every action is locally executable.

Sources:

- [OpenConnector repository](https://github.com/oomol-lab/open-connector)
- [Catalog and local-execution status](https://github.com/oomol-lab/open-connector/blob/main/docs/catalog-format.md)
- [Gmail provider](https://github.com/oomol-lab/open-connector/tree/main/src/providers/gmail)
- [GitHub provider](https://github.com/oomol-lab/open-connector/tree/main/src/providers/github)
- [Spotify provider](https://github.com/oomol-lab/open-connector/tree/main/src/providers/spotify)

**Current assessment:** strongest implementation reference and possible focused
donor, but not a replacement runtime unless Marvi deliberately delegates the
entire account authority to it.

### Option D — Zapier Connectors

Zapier's connector artifact combines an agent skill with MCP-shaped TypeScript
tools. A connector can run in-process, as a CLI, or as a local MCP server and
can use direct user-held credentials or Zapier-managed connections.

**Strengths**

- Attractive “one connector folder, many runtimes” packaging model.
- In-process TypeScript execution is possible.
- Skills, schemas, references, and executable actions live together.

**Weaknesses**

- The repository explicitly calls itself a prototype with an unstable pre-1.0
  contract.
- Elastic License 2.0 is not an OSI open-source license and restricts offering
  the software as a hosted or managed service.
- The visible first cohort is small relative to Zapier's advertised platform
  catalog and does not cover the complete requested provider set.
- Zapier-managed authentication recreates the same hosted dependency question
  as Composio.

Sources:

- [Zapier Connectors README](https://github.com/zapier/connectors/blob/main/README.md)
- [Current connector folders](https://github.com/zapier/connectors/tree/main/apps)
- [Elastic License 2.0](https://github.com/zapier/connectors/blob/main/LICENSE)
- [Zapier Platform](https://github.com/zapier/zapier-platform)

**Current assessment:** study the artifact shape; do not use it as Marvi's
connector foundation today.

### Option E — Metorial

Metorial is a self-hostable MCP-oriented access control plane with OAuth,
identity, permissions, and observability.

**Strengths**

- Broad server and integration catalog.
- Centralized credentials, audit, RBAC, and MCP sessions.
- Self-hosting is supported.

**Weaknesses**

- It duplicates Gateway's account, permission, and audit authority.
- It is operationally shaped as a platform, not an embedded desktop library.
- The platform is currently under FSL-1.1-ALv2; it becomes Apache-2.0 two years
  after each release. The catalog and the platform do not have the same
  immediate licensing meaning.

Sources:

- [Metorial repository](https://github.com/metorial/metorial)
- [Metorial platform license](https://github.com/metorial/metorial/blob/main/LICENSE)

**Current assessment:** reject for Marvi's local built-in Accounts path.

### Option F — Nango

Nango focuses on product integrations, managed OAuth, authenticated proxying,
and TypeScript integration functions.

**Strengths**

- Mature OAuth and refresh-token focus.
- Large API catalog and white-label connection UX.
- Proxy and integration-function primitives.

**Weaknesses**

- It is an integration platform and runtime, not an in-process connector SDK.
- Self-hosting adds infrastructure and operating responsibility.
- The repository uses the Elastic License and reserves capabilities for paid
  hosted or enterprise offerings.
- It would replace Composio with another credential/control service rather
  than eliminate the dependency class.

Source: [Nango repository](https://github.com/NangoHQ/nango).

**Current assessment:** reject for the stated native/local requirement; revisit
only if Composio fails and a managed OAuth platform remains acceptable.

### Option G — Activepieces, Pipedream, and n8n

These projects contain valuable integration implementations, but their full
workflow runtimes are much larger than Marvi's connector need.

- Activepieces' non-enterprise code is MIT and its pieces may be useful as
  individually reviewed references, but its production architecture includes
  an application, workers, sandboxes, Postgres, and Redis:
  [architecture](https://github.com/activepieces/activepieces/blob/main/docs/install/architecture/overview.mdx),
  [license](https://github.com/activepieces/activepieces/blob/main/LICENSE).
- Pipedream publishes a large component catalog, but its repository uses the
  Pipedream Source Available License and restricts commercial use:
  [repository](https://github.com/PipedreamHQ/pipedream),
  [license](https://github.com/PipedreamHQ/pipedream/blob/master/LICENSE).
- n8n's Sustainable Use License specifically explains that using users' own
  credentials to power a product feature is not allowed without a commercial
  agreement:
  [license guidance](https://github.com/n8n-io/n8n-docs/blob/main/docs/privacy-and-security/sustainable-use-license.md).

**Current assessment:** do not embed the platforms. Review a focused,
permissively licensed component only when it directly reduces implementation
work for a selected native connector and record its provenance.

## The unavoidable one-click connection constraint

A managed catalog does not by itself solve desktop secret distribution.

Today the user enters a Composio project API key into Marvi. This preserves a
local product deployment because the user owns the hosted Composio account, but
it is not the one-click experience offered by Claude.

For Marvi to ship “Connect Gmail” with no developer setup, a protected service
must hold the Composio project credential and create scoped connection links.
Embedding a reusable project secret in Electron or the local Gateway is not a
security boundary; a user or attacker controlling the machine can extract it.

The feasible product models are:

1. **Bring your own Composio project.** Fully compatible with the current local
   architecture, but setup remains technical.
2. **Minimal Marvi connector broker.** A Marvi-operated service protects the
   Composio project credential and issues bounded connect/session material.
   This provides the easiest UX but introduces hosted infrastructure, account
   identity, abuse controls, cost, privacy disclosures, and availability work.
3. **Provider-native OAuth.** Marvi ships public/native OAuth client IDs and
   stores user tokens locally. This avoids a Marvi server for providers that
   support public clients, but reintroduces connector implementation and
   provider verification.
4. **A Composio client-safe capability.** Investigate whether the selected
   Composio product and plan offers a publishable or otherwise desktop-safe
   connection primitive. Do not assume that a server API key is safe to ship.

There is no design that simultaneously provides all three without someone
operating the missing trust boundary:

```text
no hosted infrastructure
+ no user developer/account setup
+ hundreds of managed OAuth connectors
```

## Proposed direction for deeper investigation

### Product architecture

```text
Accounts UI
    -> Electron main capability bridge
    -> Marvi Gateway Connector Broker
        -> ComposioConnectorBackend
            -> official Composio SDK
            -> hosted auth/actions/triggers
            -> provider APIs
```

The names are illustrative. The important constraint is that renderer, voice,
ARC, and memory depend on a Marvi-owned connector interface rather than on
Composio SDK types or action semantics.

### Proposed Gateway interface

```python
class ConnectorBackend(Protocol):
    def catalog(self, query: str = "", limit: int = 100) -> list[Connector]: ...
    def connections(self) -> list[Connection]: ...
    def authorize(self, connector: str) -> Authorization: ...
    def reconnect(self, connection_id: str) -> Authorization: ...
    def disable(self, connection_id: str) -> None: ...
    def revoke(self, connection_id: str) -> None: ...
    def search_tools(self, query: ToolQuery) -> list[ConnectorTool]: ...
    def execute(self, request: ConnectorExecution) -> ConnectorResult: ...
```

The interface must also expose or support:

- stable connector and connection IDs;
- multiple accounts per provider;
- exact granted scopes;
- reviewed action effects;
- idempotency keys or explicit unsupported status;
- canonical resource URLs and provenance;
- reconnect and rate-limit classifications;
- health without exposing credentials; and
- trigger/poll capability without assuming one transport.

### Stable agent tools

The current progressive-discovery idea should remain. Candidate names are:

- `connector_status`
- `connector_search`
- `connector_execute`

The migration may retain aliases for `accounts_status`, `account_tool_search`,
and `account_tool_execute`. The voice prompt must not contain the entire remote
catalog.

### Marvi-owned policy overlay

Marvi should maintain a small reviewed overlay for high-value actions rather
than fork their implementations:

```yaml
GMAIL_FETCH_EMAILS:
  effect: read
  confirmation: false
  result: untrusted_resource

GMAIL_SEND_EMAIL:
  effect: external_write
  confirmation: model_selected_in_confirm_mode
  idempotency: required

GOOGLECALENDAR_DELETE_EVENT:
  effect: destructive_external_write
  confirmation: model_selected_in_confirm_mode
  ambiguous_retry: forbidden
```

This overlay does not contradict Confirm/YOLO. It supplies truthful tool
behavior to the existing user-selected confirmation policy; it must not become
a hidden fixed risk matrix that overrides those modes.

### Product presentation

The Accounts page should eventually present:

- “Marvi Connectors,” not “Connect Composio” as the primary product heading;
- a technical disclosure that a connector is powered by Composio where true;
- connection identity and account alias;
- requested and granted capabilities;
- read/write/admin ceiling;
- memory auto-fetch state and health;
- reconnect, disable, and revoke;
- last successful operation and useful error state; and
- whether data and credentials are local or hosted.

Composio remains explicitly named in About, diagnostics, privacy documentation,
technical logs, dependency inventory, and the upstream ledger.

### Plugins built above connectors

A future Marvi plugin may declare connector dependencies without implementing
their OAuth or action transport:

```text
plugin/
├── manifest.json
├── skills/
├── workflows/
├── connector-requirements.json
├── optional-agents/
└── references/
```

Example: a “morning operator” plugin could require read access to Gmail,
Calendar, and GitHub, provide a deterministic briefing workflow, and expose an
optional send/update phase. Credentials remain owned by Accounts, never by the
plugin. Installing a plugin must not silently expand account scopes.

## Recommendation under consideration

The current preferred direction is:

1. Keep Composio as the default maintained connector engine.
2. Make the user-facing capability “Marvi Connectors.”
3. Introduce a narrow provider-neutral Gateway seam before expanding behavior.
4. Keep Marvi's existing confirmation, audit, idempotency, untrusted-content,
   memory, and ARC boundaries authoritative.
5. Maintain reviewed policy metadata for important actions without forking
   their implementations.
6. Fix the shared `default` identity and unpinned action versions.
7. Decide the one-click connection trust model before changing first-run UX.
8. Add a native provider only after a measured Composio limitation justifies
   its permanent maintenance burden.
9. Treat OpenConnector and Zapier Connectors as research inputs, not runtime
   dependencies at this stage.
10. Keep MCP available for custom interoperability but out of built-in
    connector presentation and the foreground agent prompt.

## When a native provider would be justified

A built-in provider implementation should require evidence for at least one of
these conditions:

- Composio lacks required actions or returns inadequate schemas.
- Latency materially harms the voice interaction.
- Reliability or rate limits fail an acceptance gate.
- Privacy or compliance forbids hosted credential/action handling.
- Per-call or per-user cost becomes material.
- Offline or LAN-only access is required.
- A provider offers a maintained official SDK that removes most implementation
  burden.
- A strategic provider needs product-specific behavior that cannot be expressed
  through the Composio action contract.

Even then, the native provider should implement the same `ConnectorBackend`
contract so Accounts, ARC, and the agent surface do not fork.

## Questions to answer before planning

### Product and business

1. Is Marvi a personal project where users may bring their own Composio key, or
   a distributable consumer product that requires one-click Accounts?
2. Is a minimal Marvi-hosted connector broker acceptable despite the local-only
   media and desktop-runtime philosophy?
3. What connector usage and cost model is acceptable per active user?
4. Which providers are launch-critical versus attractive catalog breadth?
5. Does “native” mean Marvi-owned UX/policy or locally held provider tokens?

### Composio due diligence

1. Which plan and SDK/API generation should Marvi target?
2. What are the current limits, pricing dimensions, retention rules, regional
   processing options, deletion guarantees, and incident commitments?
3. Can Marvi use its own provider OAuth applications while Composio maintains
   connection state?
4. Is there a desktop-safe connect/session primitive that does not expose a
   reusable project secret?
5. Can tool and toolkit versions be pinned per environment and advanced through
   a changelog/canary process?
6. What idempotency guarantees exist for write actions?
7. How are ambiguous timeouts reported?
8. Can provider tokens be exported or migrated if Marvi changes backend?
9. What trigger guarantees exist: ordering, retries, deduplication, retention,
   polling intervals, and signature rotation?
10. How are deleted/revoked connections and stored provider data erased?

### Architecture

1. Should the seam be called `ConnectorBackend`, `AccountBackend`, or something
   else consistent with existing Gateway terminology?
2. Is backend selection global, per provider, or per connection?
3. How should existing Composio connection IDs migrate to stable Marvi IDs?
4. Should one Google authorization appear as one Workspace account with Gmail,
   Calendar, and Drive capability packs, or as separate connector cards?
5. How will account aliases be selected in voice without guessing?
6. Where does the reviewed action-effect overlay live and how is it tested
   against the live catalog?
7. How will plugin connector requirements request scope changes without silent
   privilege expansion?

### Testing and evidence

1. Which sandbox accounts can be maintained for Gmail, Calendar, Drive, GitHub,
   Slack, Notion, and Spotify?
2. What live acceptance suite runs before a Composio SDK or toolkit upgrade?
3. How will destructive actions be exercised safely?
4. What proves idempotency after a timeout or Gateway restart?
5. What latency budget is acceptable for voice connector discovery and
   execution?
6. How long must trigger and polling soak tests run?
7. What provider data may appear in logs, fixtures, and CI artifacts?

## Suggested investigation sequence

This is research order, not an implementation phase commitment.

### Gate 1 — Composio commercial and security due diligence

- Obtain exact answers to the Composio questions above.
- Test project isolation with two Marvi installation identities.
- Verify deletion, revocation, and reconnect behavior.
- Measure discovery and execution latency for representative reads and writes.
- Confirm toolkit version pinning and upgrade mechanics.
- Record results with the tested SDK, toolkit versions, account type, date, and
  Marvi commit.

### Gate 2 — one-click UX feasibility

- Decide BYO Composio versus a minimal Marvi broker.
- Threat-model desktop extraction of project credentials.
- Document data flow and privacy disclosure.
- Prototype the shortest secure Connect flow without changing production
  Accounts.

### Gate 3 — provider-neutral seam design

- Specify typed connection, tool, execution, error, and result contracts.
- Prove the existing Composio implementation can satisfy the seam without
  losing behavior.
- Prove Accounts, auto-fetch, ARC triggers, and tool registration can depend on
  the seam without a second authority.
- Define backward compatibility for current routes and tool names.

### Gate 4 — curated connector behavior

- Choose a small launch set.
- Add reviewed capability/effect metadata.
- Add source URLs and resource identity to read results.
- Add live sandbox behavior tests for basic flow, intended tool call, error,
  reconnect, confirmation, workflow transition, and ambiguous writes.

### Gate 5 — plugin model

- Specify a non-executable manifest first.
- Define connector requirements and scope-upgrade UX.
- Define trust, signatures, updates, and uninstall behavior.
- Do not allow plugins to carry credentials or bypass Gateway tools.

## Documentation and contract changes required if accepted

An accepted implementation would need one coherent milestone updating:

- `AGENTS.md`: revise “Composio owns supported third-party OAuth connections
  and account tools” to the selected connector authority contract.
- `docs/ARCHITECTURE.md`: add the provider-neutral seam and selected secret
  boundary.
- `docs/DECISIONS.md`: add an ADR that supersedes or refines ADR-024.
- `docs/PLAN.md` and the relevant phase file: add acceptance gates and evidence.
- `docs/UI.md`: define Marvi Connectors presentation and hosted/local disclosure.
- `docs/UPSTREAM.md`: pin every adopted SDK, repository, version, license, and
  modification boundary.
- `README.md`: describe only the connector behavior actually shipped.
- `docs/IMPLEMENTATION-LOG.md`: record the completed milestone and evidence.

The implementation must include behavior tests and real provider sandbox
evidence before the milestone is committed.

## Risks

| Risk | Mitigation to investigate |
| --- | --- |
| Composio outage disables connectors | Isolated degradation, cached connection status, clear health, no effect on core voice |
| Vendor lock-in | Provider-neutral seam, Marvi IDs, versioned schemas, migration/export due diligence |
| Desktop project-key extraction | BYO project or protected broker; never embed a reusable secret |
| Schema change causes wrong action | Pin versions, reviewed upgrade, live sandbox suite |
| Duplicate external write | Idempotency key where supported; ambiguous result state; no blind retry |
| Wrong account selected | Stable connection IDs and explicit aliases; never infer identity from display names |
| Prompt injection from email/web tools | Existing structural untrusted envelope and source provenance |
| Hosted data conflicts with local expectations | Explicit Accounts, privacy, About, and diagnostics disclosure |
| Plugin expands privilege silently | Connector requirements are declarative and every new scope requires Accounts authorization |
| Catalog size harms voice latency | Progressive search/execute tools and small task-scoped toolsets |

## Provisional conclusion

The strongest current conclusion is not that no ready connectors exist. Ready
connectors do exist, but the maintained breadth, OAuth convenience, and edge
handling live in platforms rather than in a small local library.

For Marvi, Composio is presently the most defensible upstream because it is
already integrated and lets the project avoid becoming an integration company.
The design opportunity is to make connectors native to Marvi's product and
policy while keeping the engine replaceable:

```text
Native Marvi experience and authority
    + maintained Composio integration engine
    + explicit hosted-service disclosure
    + narrow replaceable Gateway seam
    + evidence-driven native exceptions only
```

This conclusion remains provisional until the one-click credential model,
Composio commercial/security due diligence, version pinning, data migration,
and live acceptance strategy are answered.
