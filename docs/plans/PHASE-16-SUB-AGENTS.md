# Phase 16 Sub-agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Marvi hands multi-step work to Harvi (coding), Jarvi (computer use), Talos (browser use) or a generic worker, returns in the same turn, and hears the result on a later turn.

**Architecture:** Agents are prompt-registry files (`prompts/<name>.md`) with agent frontmatter. `subagents.py` runs each job on a background thread with its own message list, over `ProviderClient.call_with_fallback` and the Gateway's audited `dispatch_for_chat`. Results reach voice through the existing `delegated.py` watcher; confirmations park the job until any approval path settles the token.

**Tech Stack:** Python 3.12, FastAPI Gateway, LiveKit Agents voice worker, pytest.

**Spec:** [`docs/phases/16-sub-agents.md`](../phases/16-sub-agents.md)

## Global Constraints

- Built-in names are exactly `harvi`, `jarvi`, `talos`; generic is `worker`.
- Blocked for every sub-agent: `delegate`, `delegate_stop`, `delegate_steer`, `delegate_approve`, `delegate_to_coder`, `memory_remember`, `memory_forget`, `note_about_user`, `telegram_send`, `send_email`, `speak`, `end_conversation`, `cronjob`, `schedule_add`, `clarify`, `ask_secret`.
- Concurrency: 3 jobs total, 1 `jarvi`, 1 `talos`.
- Stall: 450 s without a model call or tool result. Circuit breaker: 3 identical failing calls.
- Last round offers no tools. Only the final summary returns to Marvi.
- Confirm mode parks a job as `awaiting_approval`; YOLO never parks.
- Harvi's prompt text is adapted in Marvi's voice from the Piebald collection; no verbatim Claude Code text.
- Every behaviour change ships with a test; `git diff --check` before commit.

## File map

| File | Responsibility |
|---|---|
| `services/gateway/src/marvi_gateway/prompts.py` | Parse `tools`, `model`, `max-rounds` agent frontmatter |
| `prompts/harvi.md`, `jarvi.md`, `talos.md`, `worker.md` | Agent definitions |
| `services/gateway/src/marvi_gateway/subagents.py` | Job, Runner, loop, contract, tools registration |
| `services/gateway/src/marvi_gateway/workspace.py` | `file_read` ranges, `glob`, `grep`, `terminal_run` background, `process_output` |
| `prompts/tools/{delegate,delegate_stop,delegate_steer,delegate_approve,glob,grep,process_output}.md` | Tool descriptions |
| `services/gateway/src/marvi_gateway/app.py` | Build Runner, register tools, hook confirmation settle |
| `services/agent/src/marvi_agent/tools.py` | Drop multi-step computer/browser tools from voice; watch `delegate` jobs |
| `services/agent/src/marvi_agent/delegated.py` | Surface `awaiting_approval` once per token and keep watching |
| `skills/delegating-to-a-coding-agent/SKILL.md`, `skills/computer-use`, `skills/browser-use` | Marvi delegates; agents carry the how-to |
| Docs | ADR-028, UPSTREAM, ARCHITECTURE, README, phase 16, IMPLEMENTATION-LOG |

## Interfaces

```python
# prompts.py
@dataclass(frozen=True)
class Prompt:
    ...
    tools: tuple[str, ...] = ()      # "*" means every tool
    model: str = ""                  # provider job role, "" = main
    max_rounds: int = 0              # 0 = runner default

# subagents.py
BLOCKED: frozenset[str]
MAX_RUNNING = 3
SINGLE = {"jarvi", "talos"}
STALL_SECONDS = 450.0
DEFAULT_ROUNDS = 25

@dataclass
class Job:
    id: str; agent: str; name: str; task: str; mode: str
    state: str = "running"     # running | awaiting_approval | completed | failed | interrupted
    exit_reason: str = ""      # completed | max_rounds | stopped | stalled | error
    summary: str = ""
    progress: str = ""
    token: str = ""; action: str = ""
    def as_dict(self) -> dict[str, Any]: ...

class Runner:
    def __init__(self, client, schemas: Callable[[], list[dict]], dispatch: Callable[[str, dict], dict],
                 settle: Callable[[str, bool], dict] | None = None,
                 on_stop: Callable[[Job], None] | None = None, root: Path | None = None) -> None
    def start(self, agent: str, task: str, mode: str = "") -> dict[str, Any]
    def status(self, job_id: str = "") -> dict[str, Any]
    def stop(self, job_id: str) -> dict[str, Any]
    def steer(self, job_id: str, message: str) -> dict[str, Any]
    def approve(self, job_id: str, approve: bool) -> dict[str, Any]
    def settled(self, token: str, outcome: dict[str, Any]) -> None   # any approval path calls this
    def wait(self, job_id: str, timeout: float) -> Job               # tests

def register_subagent_tools(registry, runner: Runner) -> None
```

## Tasks

### Task 1: Agent definitions in the prompt registry
- [ ] Test `test_prompts.py::test_agent_frontmatter_declares_tools_model_and_rounds`: parse a tmp prompt with `when-to-use`, `tools` list, `model: aux`, `max-rounds: 40`; assert fields. Run, see it fail.
- [ ] Add fields to `Prompt`, collect `tools` as a list in `_parse`, read `model`, `max-rounds` (int, default 0).
- [ ] Write `prompts/harvi.md`, `jarvi.md`, `talos.md`, `worker.md`. Test `test_built_in_agents_exist` asserts `prompts.agents()` contains all four with non-empty tools.

### Task 2: The runner
- [ ] Tests in `services/gateway/tests/test_subagents.py` using a sequenced fake client and a recording dispatch:
  - completes and returns the final text as `summary`; intermediate tool output absent;
  - allowlist filters schemas; blocked tools never offered and refused if called;
  - last round offered `tools=None`; exit `max_rounds`;
  - three identical failures → `failed`;
  - stop → `interrupted/stopped`; steer text appears in the next request;
  - concurrency caps (4th job refused; 2nd jarvi refused);
  - confirmation parks, `settled(token, executed)` resumes with the result, deny resumes with a denial;
  - Harvi `investigate` offers no write tools; `file_edit` refused before `file_read` of that path;
  - `todo_write` updates `progress`.
- [ ] Implement `subagents.py` (loop mirrors `cognition.CognitionHarness.ask` message shape).

### Task 3: Gateway wiring
- [ ] Test `test_subagents.py::test_tools_are_registered_and_described` over a real `ToolRegistry`.
- [ ] `register_subagent_tools`: `delegate`, `delegate_stop`, `delegate_steer`, `delegate_approve`; extend `delegated_status` to look in the runner first, then `delegate.status`.
- [ ] `app.py`: build `Runner(provider_client, schemas_from_registry(tool_registry), dispatch_for_chat, settle=..., on_stop=...)`; call `runner.settled` from `resolve_confirmation` and `settle_for_channel`; Jarvi stop issues `computer_control stop`.

### Task 4: Coding tools
- [ ] Tests in `test_workspace*.py`: `file_read` offset/limit numbered lines; `glob` newest-first; `grep` modes/context/type/case/head_limit; `terminal_run(background=True)` then `process_output`.
- [ ] Implement in `workspace.py`; add `prompts/tools/*.md`.

### Task 5: Voice
- [ ] Tests in `services/agent/tests/test_voice_tools.py`: catalogue drops `computer_action`, `computer_tools`, `browser_action`, `browser_read_image`, `browser_save_download`; keeps `computer_status`, `computer_control`, `browser_open`, `browser_status`, `browser_control`; a `delegate` result is watched.
- [ ] `test_delegated.py`: `awaiting_approval` surfaced once per token, watching continues to completion.
- [ ] Implement.

### Task 6: Skills and docs, then commit
- [ ] Update skills, ADR-028, UPSTREAM, ARCHITECTURE, README, phase 16 evidence, IMPLEMENTATION-LOG.
- [ ] Run gateway + agent suites; `git diff --check`; commit `feat: add Harvi, Jarvi and Talos sub-agents`.
