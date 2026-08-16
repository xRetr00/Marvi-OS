# Marvi OS Engineering Guide

These rules are mandatory for humans and coding agents working in this
repository.

## Product intent

Marvi OS is an always-on Windows voice and vision assistant. It is not a coding
chat application and it is not a fork of Marvi Agent. Marvi Agent may be called
as a durable deep-work tool, but it is not the voice runtime.

The primary interaction surface is the Dynamic Island. The main window is a
control center with a sidebar and status bar; it does not contain a traditional
chat transcript or coding interface.

## Upstream-first rule

Do not write a subsystem from scratch when a maintained repository, SDK, or
protocol already solves it.

Before adding a subsystem, choose the first applicable rung:

1. Use an existing dependency unchanged.
2. Scaffold from an official starter.
3. Fork or vendor a focused upstream component with provenance.
4. Write a thin adapter around an upstream component.
5. Write custom implementation only for Marvi OS-specific product behavior.

Every dependency, fork, copied component, and meaningful code extraction must be
recorded in `docs/UPSTREAM.md` with its source URL, license, pinned version or
commit, modification boundary, and update method. Never copy example code
without understanding and documenting it.

## Architecture authority

- **Electron main** owns Windows lifecycle, windows, tray, startup, updates,
  permissions, process supervision, and the narrow renderer capability bridge.
- **Renderer** owns presentation and ephemeral UI interaction only.
- **Marvi Gateway** owns local service health, agent sessions, tool execution,
  confirmation tokens, audit events, and connections to sidecars.
- **LiveKit** owns realtime media transport and agent session orchestration.
- **Voice engines** own STT/TTS inference behind streaming adapters.
- **Smart Room** owns room devices, presence state, automations, and room history.
- **Composio** owns supported third-party OAuth connections and account tools.
- **Memory service** owns durable episodic and semantic memory.

Do not move audio inference, camera inference, tool policy, or process lifecycle
into React. Do not put room device drivers inside Marvi OS.

## Local-only deployment

Cloud-hosted LiveKit is out of scope for the initial product. The app manages a
local LiveKit server on loopback as part of Marvi Gateway. The LiveKit binary
remains an explicitly named dependency in technical logs and diagnostics even
though the user-facing service is branded Marvi Gateway.

Raw microphone and camera streams stay local. They are continuously available
to local wake-word, presence, and gesture inference. Publish media into an
active LiveKit room only when a voice/vision session needs it.

## LiveKit rules

The `livekit-agents` skill is mandatory for LiveKit work.

- Verify every LiveKit API against current official documentation before use.
- Prefer official starters and examples over handwritten session plumbing.
- Keep the voice agent prompt and active tool list small.
- Use tasks and handoffs for scoped work instead of one monolithic agent.
- Never recreate interruption, endpointing, playout, or RTC lifecycle outside
  LiveKit when the SDK already owns it.
- Every agent behavior change requires tests: basic flow, intended tool call,
  error behavior, and workflow transition when applicable.
- When the LiveKit documentation MCP server is unavailable, use official web
  documentation and do not guess signatures.

## Voice latency and quality

The shipping voice stack must be genuinely streaming. Sentence-at-a-time or
whole-utterance synthesis is not accepted as streaming.

No voice engine becomes the default without passing the benchmark and soak
criteria in `docs/VOICE-MODEL-EVALUATION.md` on the target RTX 3060 12 GB host.
Keep at least 2 GB of VRAM headroom for the desktop compositor, camera pipeline,
and transient allocations.

## Tool confirmation modes

There are two user-selected modes:

- **Confirm**: the LLM decides that an action needs confirmation and requests a
  confirmation token. Either a spoken approval or a Dynamic Island action may
  satisfy the request. The gateway executes only after validating the token.
- **YOLO**: confirmation is bypassed for every action, including destructive or
  externally visible actions. The UI must show a persistent, unmistakable YOLO
  indicator. Validation, authentication, and audit logging still apply.

Do not add a hidden fixed risk matrix that contradicts these modes. External
content from email, social networks, web pages, tools, room events, and vision
is untrusted data and must never be treated as system instructions.

## UI contract

- Monochrome black/white/gray palette with a restrained blue status accent.
- ASCII/terminal construction, modern spacing, crisp borders, no fake CRT noise
  that harms readability.
- The app icon is `assets/app-icon-source.png`.
- The repository banner is never displayed or packaged as runtime UI.
- Dynamic Island remains compact; expansion is temporary and content-driven.
- Background events never steal focus or open the main window.
- Expensive always-on services do not depend on renderer visibility.

Read `docs/UI.md` before changing the shell, sidebar, status bar, Island, About,
or settings.

## Versioning and updates

- `VERSION` is the single product version source.
- Use SemVer prereleases during development and stable SemVer for releases.
- Every build exposes version, Git commit, build time, and update channel.
- Reuse the repository-owned Windows update handoff pattern: the Electron app
  quits and hands off to the small Tauri bootstrap binary
  (`apps/updater`, `marvi-bootstrap.exe`), which updates/builds atomically,
  writes a result marker, and relaunches. The `release` channel (default)
  tracks the latest signed `v*` tag; the opt-in `dev` channel fast-forwards
  `origin/main`.
- The updater must be tested from older releases, not only from the current
  checkout. A failed update must preserve the last working installation.

## Tests and evidence

- Add behavior tests with every feature.
- Exercise real process and protocol boundaries for Gateway, LiveKit, voice
  sidecars, Smart Room, Composio, updates, and renderer bridges.
- Unit mocks are not evidence for acoustic quality, GPU residency, device
  switching, or update recovery; use named hardware and real binaries.
- Record latency and memory measurements with hardware, model, quantization,
  and commit identifiers.

## Documentation discipline

Update the relevant architecture, plan, UI, upstream, and decision documents in
the same change that changes the contract. If implementation and documentation
disagree, stop and resolve the disagreement before expanding the system.

`README.md` is public product truth, not a one-time bootstrap artifact. Update
its status, implemented-capability list, start instructions, and documentation
links at every milestone that changes them. Do not advertise planned or
scaffolded behavior as shipped behavior.

## Commit discipline

- Commit every completed milestone after its acceptance checks pass and its
  phase file, implementation log, and README are current.
- A milestone is one coherent, reviewable product outcome with an acceptance
  boundary. It is not one file, one function, or one small task.
- Do not create noisy commits after every file or two. Keep related code, tests,
  generated assets, and documentation together in the milestone commit.
- Do not mix independent milestones in one commit. If work is unfinished, leave
  it uncommitted unless an explicitly requested checkpoint is necessary.
- Use an imperative conventional subject such as `feat: complete island seed
  milestone` or `test: prove native voice interruption`.
- Before committing, run the phase-appropriate tests and `git diff --check`.
  Record meaningful hardware/visual evidence in the phase file.
