# Mind and Proactivity Research Review

The supplied research is strong input for Marvi OS's later Mind/Cortex work,
but none of it belongs in the Phase 3 audio hot path. Phase 3 stays a
deterministic LiveKit voice pipeline; cognition subscribes to its events later.

## What we will use

- **ContextAgent** supplies the basic proactive decision shape: sensory and
  world context plus persona produce a necessity decision before tool use.
- **Galaxy** is useful for a hierarchical context/cognition model and its
  explicit privacy boundary. Its implementation is research reference, not a
  runtime dependency.
- **ProAgent** provides the most applicable perception policy: begin with cheap
  signals and request richer sensing only when uncertainty or relevance warrants
  it. This maps directly to mmWave → microphone → camera escalation.
- **ProAgentBench** is the basis for scenario evaluation: long-running event
  streams, both correct interventions and correct silence, and privacy failures.
- **ProactiveAgent** provides concrete ActivityWatcher/event/proposal and
  accept/reject/ignore feedback patterns. Its older Conda and extension stack is
  not suitable as a Marvi OS dependency.
- **Letta Agent SDK** is the preferred candidate for persistent identity and
  memory blocks. Its official LiveKit plugin makes it viable without replacing
  LiveKit's realtime media loop. It must be benchmarked against a simpler local
  memory implementation in Phase 5 before adoption.
- The voice-interruption papers inform evaluation of timing, spoken
  interruptions, and graceful barge-in. They are test-design references, not
  packages.

## Architectural consequence

The Mind receives normalized events and produces proposals. A policy boundary
decides whether to stay silent, notify, ask, or act. The realtime session never
waits on long-term memory indexing or proactive reasoning. User feedback on a
proposal is durable training/evaluation data, not an opaque self-modifying rule.

## Deferred evaluation gates

Before Letta or any proactive runtime is adopted, Phase 5–6 must measure idle
CPU/RAM, retrieval latency, context correctness, privacy filtering, duplicate
proposal rate, correct-silence rate, and recovery after restart. Integrations
with email or social accounts remain Composio-backed tools behind Marvi's
confirmation policy.

## Primary sources

- [ContextAgent](https://arxiv.org/abs/2505.14668)
- [Galaxy](https://arxiv.org/abs/2508.03991)
- [ProAgent](https://arxiv.org/abs/2512.06721)
- [ProAgentBench](https://arxiv.org/abs/2602.04482)
- [THUNLP ProactiveAgent](https://github.com/thunlp/ProactiveAgent)
- [Letta Agent SDK](https://github.com/letta-ai/letta-agent-sdk)
- [LiveKit Letta plugin](https://docs.livekit.io/agents/models/llm/letta/)

