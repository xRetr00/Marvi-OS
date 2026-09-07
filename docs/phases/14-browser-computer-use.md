# Phase 14 — Agent browser and computer use

Status: planned. Review completed 2026-09-07 against repository commit
`0d223fa4` and current upstream documentation. No runtime implementation or
hardware qualification is claimed by this review.

## Outcome

Give Marvi a persistent local browser with tabs, actionable observations, and
user takeover; then add Windows application control through a maintained
upstream tool server. Keep tool execution and confirmation in Gateway.

An agent browser still uses tools. The difference is a managed browser session
plus a repeatable observe, act, verify loop. Search/fetch retrieves documents;
a browser runs JavaScript and maintains cookies, forms, tabs, and page state.
Neither requires embedding a second chat application in Marvi.

## Current implementation review

| Area | Evidence | Finding |
|---|---|---|
| Real browser | `services/gateway/src/marvi_gateway/browser.py`, `BrowserSession._launch` | Already launches Chromium through Playwright; headless by default, enabled with `MARVI_BROWSER`. |
| Session | `_current`, `_launch` | One shared page and a fresh nonpersistent context; no profile, task ownership, tab selection, or takeover contract. |
| Observation | `_snapshot`, `links` | Body text limited to 12,000 characters and links; no actionable element references. Click/fill require selectors the observation does not supply. |
| Interaction | `click`, `type_text`, `back` | Basic interactions exist; popup/tab selection, explicit scrolling, select controls, upload/download workflows, and verification are missing. Dialogs are dismissed and downloads refused. |
| Images | `browser_screenshot`, `mcp_bridge.py:call` | Browser capture returns a file path. MCP blocks are converted to text/string representations, so installing a vision-capable server does not establish a working image path. |
| Network boundary — high priority | `open` calls `assert_public_http_url` once | The initial URL is checked. Redirects, click navigation, subresources, popups, and browser DNS resolution are not covered by that check. ADR-017's claim that every navigation is guarded is inaccurate. This is a code finding, not an exploit demonstration. |
| Confirmation — contract mismatch | Browser ToolSpec flags, `app.py` tool dispatch, `mcp_bridge.py` annotations | Click/type always request confirmation in Confirm mode. AGENTS.md instead requires the LLM to decide when to request a token. Upstream read-only hints must not become the product's hidden risk matrix. |
| Tests | `services/gateway/tests/test_browser.py` | Fake-session tests cover wrapping and confirmation. The real Chromium test drives private page internals against loopback and checks text/links; it does not prove the public Gateway navigation boundary or real form actions. |
| Existing computer tools | `workspace.py`, `screen.py` | File list/search/read/write/edit/delete, terminal execution, process list/stop, and primary-display vision Q&A already exist. Screen Q&A is not desktop interaction. |
| MCP integration | `mcp_bridge.py` | Local stdio already works. Rich schemas are flattened to basic argument types; nested constraints and image/resource content need preservation. Context managers are entered without retained teardown ownership. |

The first implementation milestone must reconcile these discrepancies before
expanding capabilities. Untrusted envelopes label provenance; they do not
guarantee that a model resists prompt injection.

## Web comparison and upstream choice

These are design recommendations, not benchmark results. Sources were read on
2026-09-07; pin and inspect the actual release used by the spike.

| Upstream | What it supplies | Proposed role |
|---|---|---|
| [Microsoft Playwright MCP](https://github.com/microsoft/playwright-mcp) | Accessibility snapshots, browser actions, persistent profiles, and an extension for existing authenticated tabs | First browser candidate: use unchanged behind a thin Gateway adapter. Existing Playwright Python remains the baseline until this passes acceptance. |
| [Browser Use](https://github.com/browser-use/browser-use), [browser parameters](https://docs.browser-use.com/open-source/customize/browser/all-parameters) | Browser session configuration and an agent framework; local and cloud options | Comparison candidate if task success with the first option is inadequate. Its autonomous executor must not bypass Gateway action authorization. Do not introduce a second planner by default. |
| [Vercel agent-browser](https://github.com/vercel-labs/agent-browser) | CLI with compact interactive snapshots and element references | Alternative for delegated deep-work workflows. Compare total tool/model latency and context size; do not ship two interchangeable browser controllers initially. |
| [CursorTouch Windows-MCP](https://github.com/CursorTouch/Windows-MCP) | Desktop snapshots, pointer/keyboard actions, display metadata, and selectable tools over MCP | First computer-use spike: existing server, local stdio, selected capabilities. It is a third-party project, not a Microsoft product. Current docs require Python 3.13+ and note an English-language prerequisite for the app tool. Verify against Marvi's bundled runtime and the user's Windows locale. |
| [pywinauto](https://github.com/pywinauto/pywinauto) / [FlaUI](https://github.com/FlaUI/FlaUI) | Windows UI Automation and native control wrappers | Fallback thin adapter only if the MCP server fails specific acceptance gates. Python integration versus a .NET sidecar is a packaging tradeoff to measure. |
| [Microsoft UFO](https://github.com/microsoft/UFO) | Broader desktop-agent framework | Architecture reference; adopting another full orchestration stack needs evidence that the focused server is insufficient. |

Browser deployment modes:

1. **Marvi browser (default proposal):** dedicated local profile and task-owned
   tabs. Retain authenticated state locally. Explicit Open browser/Take over
   exposes the working session. Background tasks do not foreground windows.
2. **Use my browser (later opt-in):** Playwright's extension connects selected
   existing Chrome/Edge tabs. Connection consent is distinct from Marvi action
   confirmation. Never silently attach to all personal tabs or copy cookies.
3. **Remote browser:** outside this phase; not needed to deliver local control.

Chrome's [remote debugging changes](https://developer.chrome.com/blog/remote-debugging-port)
require a non-default data directory for the relevant debugging switches from
Chrome 136. Do not plan around attaching CDP to the normal profile. Validate
the extension's exact supported versions and tab-sharing behavior in the spike.

Playwright MCP explicitly states that it is not a security boundary and that
origin filters do not cover redirects. Replacing the current adapter alone
does not fix network isolation. Select and test an upstream-backed egress
boundary if retaining the public-only network contract; otherwise revise that
contract explicitly before shipping. A local browser process is not a sandbox.

## Proposed ownership and action flow

User request -> existing agent/router -> Gateway task/session -> local browser
or desktop tool server -> fresh observation -> verified result.

- Electron main supervises native processes and owns permission/UI lifecycle.
  Gateway owns session IDs, tool dispatch, cancellation, tokens, and audit.
  Renderer displays state and user actions through its narrow bridge.
- Reuse current routing; expose only the scoped browser or computer tool set
  while needed. Any future voice task/handoff implementation must use the
  mandatory LiveKit skill and verify current official APIs before coding.
- Session state includes task ID, browser profile/tab or window identity,
  observation generation, controller ownership, deadline, and cancellation.
  States: active, awaiting approval, paused for user, completed, failed, cancelled.
- Serialize actions within a browser session. Desktop input has one exclusive
  controller because mouse/keyboard and foreground state are shared. Recheck
  window identity and observation generation immediately before acting.
- Prefer account APIs through Composio, then structured browser/desktop controls,
  then screenshot-grounded pointer actions when needed. File operations use
  existing workspace tools. This is capability routing, not a risk matrix.
- Confirm mode: the model requests approval for an exact proposed action;
  Gateway validates the resulting token before execution. YOLO bypasses all
  action confirmations, including destructive/external actions, while retaining
  authentication, argument validation, audit, and the persistent YOLO indicator.
  Bind tokens to session/target as well as arguments to avoid approving an action
  on a tab or window that changed while the user was deciding.
- Re-observe after effects and report the verified outcome. Do not blindly retry
  submissions, payments, file writes, or other potentially completed mutations
  after a timeout. Return an uncertain outcome and inspect state first.
- Treat page text, desktop text, clipboard, screenshots, and tool output as
  untrusted observations. Preserve typed images separately from instructions.
  Audit target/action/result while redacting credentials and typed secrets.
- Screen Q&A currently calls the selected vision provider, which may be remote.
  Local execution does not mean local model inference. Make screen/browser
  observation routing explicit and respect configured local-only choices; do
  not change the local microphone/camera stream contract.

## Computer tool scope

| Deliver first | Reuse or defer |
|---|---|
| List windows/apps/displays; inspect bounded UI tree and selected window screenshot | Reuse screen capture where suitable; add coordinate origin, DPI, crop, and timestamp metadata. |
| Focus/launch/close selected app; invoke/select/set-value by observed reference | Reuse upstream native wrappers; no process lifecycle in React. |
| Click, drag, scroll, type, shortcuts when structured controls cannot do the job | Require fresh target observation; stop queued input when takeover/cancel occurs. |
| Explicit clipboard read/write with size bounds and no background harvesting | Use upstream clipboard capability and redact audit values. |
| Selected upload/download transfer into existing filesystem access model | Preserve default refusal until transfer paths, collision behavior, cancellation, and provenance are tested. |
| Existing file, terminal, and process tools | Do not duplicate these through Windows-MCP; expose one authoritative route. |
| Later: audio volume/device settings, app inventory, system diagnostics | Add narrow tools only for demonstrated workflows; registry editing, installer management, and broad OS administration are not first-milestone requirements. |

Windows [SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)
is constrained by integrity levels. Locked sessions, UAC/secure desktop, and
elevated windows must produce a clear unsupported/needs-user state. Do not
claim ordinary desktop input can cross these boundaries.

## Delivery and acceptance

### 14A — Reconcile current contract and establish baseline

- Correct ADR-017's network guarantee and fixed-confirmation policy against
  AGENTS.md; align dispatch and behavioral tests. Document download/dialog scope.
- Add real Gateway-process -> Chromium fixtures for navigation, form fill/click,
  redirect/private subresource attempts, cancellation, and shutdown.
- Record baseline task success, model calls/tokens, p50/p95 observation/action
  latency, browser RSS, and orphan processes. Initial URL checks are not evidence
  of full network isolation.

### 14B — Persistent browser users can take over

- Pin Playwright MCP plus browser binaries; retain the old backend as rollback
  until the candidate passes. Repair MCP typed content/schema and lifecycle
  handling with real stdio server tests before relying on the new backend.
- Deliver dedicated profile, tabs/popups, accessible references, explicit waits,
  screenshots, bounded retries, cancel, and takeover/resume with re-observation.
- Acceptance: real local fixture suite verifies multi-tab selection, login state
  across restart using a fixture account, dynamic form, stale reference, dialog,
  failed navigation, shutdown, and concurrent caller isolation. Verify Confirm,
  rejection/token mismatch/replay, YOLO, and injection attempt behavior.
- Test explicit browser opening and user takeover visually on Windows; background
  events must never steal focus. No new browser engine or Electron web container.

### 14C — Windows computer-use pilot

- Pin Windows-MCP in an isolated managed environment if its Python requirement
  differs from Gateway. Select tools and disable duplicate shell/file routes.
- Acceptance through real Gateway and server processes: Notepad text entry/save,
  Calculator result, Explorer file selection, clipboard roundtrip, window switch,
  mixed-DPI displays, negative monitor coordinates, moved/resized target, stale
  element, application crash, server crash, locked screen, and cancellation.
- Assert no further queued input after cancel is acknowledged; verify user
  takeover pauses control and requires a fresh observation before resume.
- Evaluate with the active voice workload on the RTX 3060 12 GB host. Record
  Windows/app versions, CPU/RAM, model/quantization, commit and upstream pins,
  latency and VRAM; retain at least 2 GB VRAM headroom. No acceptance based only
  on mocks or upstream latency claims.

### 14D — Product integration and extended workflows

- Add compact Island task status, Stop/Take over/Resume and existing confirmation
  actions; settings show selected browser mode and computer capability status.
  Follow `docs/UI.md`; keep background events passive and YOLO unmistakable.
- Add optional existing-browser extension mode and controlled file transfers.
- Prove a browser-to-desktop workflow, recovery after restart without replaying
  uncertain effects, and voice stop/tool errors/workflow transitions.
- Run a 30-minute mixed-task soak as an initial proposed gate: zero wrong-target
  actions, uncommanded focus changes, duplicate submissions, or orphan processes.
  Set measured latency budgets after 14A; these are not existing performance claims.

Each milestone updates implementation evidence, README capability truth,
architecture/UI/decision contracts and upstream pins, passes relevant behavior
and real-boundary checks plus `git diff --check`, then receives one coherent commit.

## Review evidence

- Read browser, MCP bridge, Gateway dispatch, workspace and screen code, browser
  tests, architecture, decision, UI, plan, and upstream documentation.
- Compared current official/project-maintained sources linked above.
- Documentation-only planning milestone: no new packages installed, no real
  browser/desktop acceptance run, and no runtime feature marked complete.
