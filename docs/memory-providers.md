# Memory providers: Honcho, Mem0, and the local store

*A plan, not an implementation. Written after fixing the local store, because
the fixes made the shape of the seam obvious.*

## Why this is worth doing at all

The local store is now roughly where Mem0 is on the one axis that was broken —
a finished turn goes to a model, which chooses `add` / `update` / `delete` /
`noop` against what is already known, off the turn. That was the whole of the
"five spellings of one name" bug.

It is nowhere near [Honcho](https://honcho.dev/docs/v3/documentation/core-concepts/architecture)
on three others, and those are not bugs to fix but a system to adopt:

| | Marvi, now | Honcho | Mem0 |
|---|---|---|---|
| Write path | async worker, LLM picks the operation | async **Deriver** | async extraction |
| Consolidation | repeat-count promotion | **Dreamer**: inductive conclusions across many messages, removes stale ones, rewrites the peer card | periodic |
| Retrieval | FTS5 keyword (embeddings pending) | semantic, and **traces a conclusion back to its premises** | semantic |
| Always present | `SOUL.md` + `USER.md`, hand-written | **peer card**, derived and kept current | — |
| Multi-agent | one store | separate **peers**, no cross-contamination | scoped |

The two that matter most are the ones we cannot cheaply build. *Tracing a
conclusion back to the premises it was drawn from* means memory can be argued
with rather than only trusted — and the Dreamer is a genuinely different idea
from our `reflect()`: it draws conclusions **across** messages rather than
counting repeats of one subject.

Worth noting: `D:\hermes-agent` does not have its own memory. Its "brain" is an
FTS5 index over *files*; real memory is a provider it delegates to. So the
thing to copy from hermes is the provider seam, not the store.

## The seam

There is already one, and it is nearly the right shape. `Rememberer.observe()`
and `MemoryStore.recall_block()` are the two calls every surface makes — voice
through `/memory/observe` and `/memory/recall`, chat directly. A provider has
to satisfy exactly those two, plus what the Memory page reads.

```python
class MemoryProvider(Protocol):
    def observe(self, user: str, assistant: str) -> None: ...
    def recall_block(self, text: str, limit: int, budget: int) -> str: ...
    def recent(self, limit: int) -> list[dict]: ...
    def forget(self, memory_id: str) -> bool: ...
    def forget_all(self) -> int: ...
```

`memory_id` becomes a string, because ours is an integer row id and theirs are
UUIDs. That is the only change the local store needs.

The tools (`memory_remember`, `memory_recall`, `memory_search`) keep working
against whichever is selected, which is what makes this a setting rather than a
migration.

## Honcho

Two deployments, and both matter for different users:

* **Managed** — `https://api.honcho.dev`, an API key. Nothing to run.
* **Self-hosted** — their Docker compose: FastAPI, Postgres with pgvector, and
  the deriver/summarizer/dreamer workers. Heavier than everything Marvi
  currently runs put together, but it stays on the machine.

Mapping:

| Marvi | Honcho |
|---|---|
| `observe(user, assistant)` | add both messages to the session; the Deriver does the rest |
| `recall_block(text)` | `get_context()` — session summary + representation + peer card |
| a hard question about the user | `chat()` — the Dialectic API, which reasons rather than retrieves |
| `USER.md` | the peer card, except derived rather than written by hand |

The interesting one is the last. If Honcho is selected, its peer card and
`USER.md` are two answers to the same question, and the honest arrangement is
that `USER.md` stays authoritative — it is user-authored and trusted, and a
derived card is not.

**One thing to check before building:** Honcho's write path is per-message and
ours is per-turn. Sending `user` and `assistant` as two messages is right;
sending them concatenated would break the Deriver's attribution of who said
what.

## Mem0

Simpler, and closer to what we have. Managed platform or self-hosted OSS, with
a vector store and an LLM behind it.

| Marvi | Mem0 |
|---|---|
| `observe(user, assistant)` | `add(messages, user_id=...)` |
| `recall_block(text)` | `search(query, user_id=...)` |
| the four operations | its own extraction, already |

Adopting Mem0 would mean deleting `remembering.py` and letting theirs decide,
which is a fair trade. **But**: Mem0 v3 regressed to ADD-only extraction and
users are filing exactly the bug we just fixed —
[#5867](https://github.com/mem0ai/mem0/issues/5867),
[#4956](https://github.com/mem0ai/mem0/issues/4956). Pin the version and test
the correction case before trusting it, rather than assuming a library is
better at this than the code it replaces.

## Order

1. **The Protocol above**, with the local store as the first implementation.
   Nothing changes for anybody; the seam exists.
2. **A `MARVI_MEMORY_PROVIDER` setting** on the Memory page beside the
   embedding one: `local` / `honcho` / `mem0`.
3. **Mem0 first**, because the mapping is one-to-one and it is a good test of
   whether the seam is real.
4. **Honcho after**, because it is the one worth having and the one whose
   shape does not fit — peer cards and the Dialectic API have no local
   equivalent, and pretending they map onto `recall_block` would waste what
   makes it good.

## What not to do

Do not run two providers at once and merge. Two systems each holding half of
what Marvi knows, with no single answer to "what do you know about me", is
worse than either alone — and it is exactly the shape of the bug we started
from: the same fact in several places, with nothing marking which is current.
