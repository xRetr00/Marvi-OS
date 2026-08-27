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
| Consolidation | repeat-count promotion, TTL sweep | **Dreamer**: inductive conclusions across many messages, removes stale ones, rewrites the peer card | periodic |
| Learning *how* | proposes a skill after a turn | — | — |
| Retrieval | keyword **and** semantic, hybrid | semantic, and **traces a conclusion back to its premises** | semantic |
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

Semantic search sits **underneath** this, not beside it. `search_similar` and
`index` are the local store's business; a provider that does its own retrieval
implements `recall_block` and never sees the embedding setting. Do not thread
embeddings through the Protocol -- Honcho and Mem0 both embed for themselves,
and a provider being handed vectors it did not ask for is a seam in the wrong
place.

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

## What we learned building the local one

Three findings that will save the next person a day, all measured on this
machine rather than assumed:

**Recall is asymmetric, and the obvious model is wrong for it.** The query is a
short first-person question; the memory is a third-person statement. MiniLM-L6
is trained for symmetric similarity and scored "who am I" against "the user's
name is Shereef" at **0.14** -- unusable -- while matching "photosynthesis" to a
note about coffee at 0.21. `bge-small-en-v1.5` with its instruction prefix
scores the same pair at **0.58** against a 0.33 field. If a provider is given
the query and passage sides without that distinction, it will be worse than the
local store at the one case this exists for.

**Absolute similarity thresholds are per-model and nearly meaningless across
them.** bge-small puts unrelated text at 0.41-0.48; e5-small puts *everything*
between 0.71 and 0.83. A threshold copied from one to the other returns either
nothing or all of it.

**Query latency is what matters, not throughput.** It is paid before Marvi can
answer. On this CPU: MiniLM 10ms, bge-small 18ms, bge-base 66ms. All are free
next to a 500ms first token, so pick on quality, not speed.

## What not to do

Do not run two providers at once and merge. Two systems each holding half of
what Marvi knows, with no single answer to "what do you know about me", is
worse than either alone — and it is exactly the shape of the bug we started
from: the same fact in several places, with nothing marking which is current.
