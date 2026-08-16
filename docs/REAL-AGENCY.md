# Real Agency and Proactivity

Marvi OS should feel alive because it notices meaningful changes, remembers,
decides, speaks, and acts—not because the UI plays a permanent "thinking"
animation. Every visible state must trace to an event owned by Marvi Gateway.

## Reuse map

| Concern | Reuse | Marvi-owned work |
|---|---|---|
| Foreground duplex conversation | LiveKit Agents sessions, tasks, tools, turn handling, and agent-state events | Local model adapters, policies, and Gateway state projection |
| Persistent mind | Evaluate Letta and `letta-voice`; use Letta Code's memory/reflection patterns as reference | Provider adapter, OpenCode Go compatibility, privacy and latency gates |
| Time-based initiative | APScheduler 3.x | Trigger policy, quiet hours, budgets, deduplication, and audit UI |
| Account context/actions | Composio SDK | Connection UI, trust policy, and normalized events |
| Room context/actions | Existing `D:\smart-room-plugin` over an MCP/event sidecar boundary | Thin adapter only; the plugin remains authoritative |
| General tools | MCP Python SDK 1.x | Permission policy and tool-result normalization |

Letta is a bakeoff candidate, not a dependency yet. Its official
`letta-voice` example proves the architectural combination with LiveKit, but
its example stack assumes cloud LiveKit, Deepgram, and Cartesia. Marvi OS must
prove native Windows, OpenCode Go, local voice models, memory export/deletion,
bounded background cost, and acceptable first-token latency before adoption.

LangGraph is a strong durable-workflow library and Temporal is a strong durable
execution system. Neither belongs in the foreground path now: adding either
would duplicate LiveKit session/task orchestration and enlarge the first
release. Revisit only when a measured workflow cannot be expressed as a
Gateway job plus a LiveKit task.

## Event-driven cognition

```text
wake speech ─────┐
room event ──────┤
account event ───┼─> Gateway event journal -> relevance/policy -> mind turn
scheduled event ─┤                                      │
memory reflection┘                                      ├─> speak/notify
                                                       └─> tool action
                                                            │
                                      exact confirmation <───┘
```

The foreground LiveKit session remains small and interruptible. Slow research,
multi-step account work, or deep delegation becomes a task whose progress is
projected as `action` state; it must never block microphone capture or barge-in.

The background mind consumes durable events. It may update memory, decide that
nothing is worth surfacing, schedule a follow-up, or create a proposed action.
It does not continuously call the LLM without a trigger.

## Proactivity contract

A proactive turn is allowed only when all of these pass:

1. The trigger is authenticated and normalized; email or web content is data,
   never executable instruction.
2. The event is new, relevant, and not suppressed by deduplication or cooldown.
3. Quiet hours, presence, current conversation, and the daily token budget permit an
   interruption.
4. The chosen output is the least intrusive useful surface: remember silently,
   update Activity, show the Island, speak, or propose an action.
5. An action follows the current confirmation mode. Confirm mode binds approval
   to the exact action token; YOLO bypasses prompts but never validation or audit.

Every decision records trigger, context references, model/provider, decision,
tool calls, confirmation token/decision, outcome, latency, and tokens locally.
Users must be able to pause initiative, inspect why Marvi spoke, and delete or
export memory.

## Acceptance gates for the mind bakeoff

- Works on native Windows without WSL2 or Docker as a product requirement.
- Uses OpenCode Go through a documented provider boundary.
- Preserves memory across restarts and supports inspect/export/delete.
- Never treats connected-account content as authority.
- Background reflection has explicit time and token budgets. The budget is
  denominated in **tokens, not money**: it is the one number every provider
  reports the same way, and the only one a subscription plan reports at all.
- Foreground interruption and audio playout remain responsive while it runs.
- A no-op decision is cheap and normal; Marvi does not speak merely to look alive.
