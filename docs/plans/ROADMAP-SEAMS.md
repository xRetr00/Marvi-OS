# Phases 12–15: one Marvi, one pipeline

We started at "refactor providers" and found that providers were the smallest
part. This is the ordered plan, written before the code, from what
`LLM-CALLERS.md` and `PROVIDER-PIPELINE.md` established.

The organising idea: **seams first.** A seam is a place where every caller must
pass. Build the seams while there are four callers to fix, then build features
once behind them. Building features first means building each one four times,
and the fourth copy is the one nobody maintains.

## The tension to design around

Two of the stated requirements pull against each other, and pretending they do
not is how this goes wrong:

- **Voice must not cold-start.** It should know who you are, what happened
  yesterday, what is in the room. That means more context on every turn.
- **Voice latency is critical.** Every token of context is time before the
  first word comes back.

So the answer is not "put everything in the prompt". It is: decide what is
*resident* (small, always there, cacheable) and what is *retrieved* (larger,
fetched only when the turn needs it), and make the resident part small enough
that it costs nothing to send every time.

That distinction is the spine of Phase 13.

---

## Phase 12 — The call seam

**Goal:** every LLM call in Marvi goes through `ProviderClient`, whoever started
the turn.

**Why first:** it is the only phase that removes work from the three after it.
Model choice, reasoning effort and auxiliary slots each become one
implementation instead of four.

1. **Measure first.** A harness that records first-token and full-response
   latency on the voice path as it is today, over enough turns to see the
   spread rather than one sample. This is the baseline the rest of the phase is
   judged against, and it has to exist before anything changes.
2. **Streaming `/llm` endpoint** on the Gateway. SSE or chunked; forwards
   provider tokens as they arrive. A buffering endpoint would move first-token
   latency from "one provider round trip" to "the whole response", which is
   unacceptable on voice and would end the phase.
3. **`GatewayLLM`** — an implementation of LiveKit's `llm.LLM` interface that
   calls that endpoint. LiveKit keeps the turn; it stops owning the provider.
   Its own plugins implement the same interface, so this is the designed
   extension point.
4. **Vision onto the registry.** `describe.py` stops using
   `MARVI_VLM_BASE_URL` / `MARVI_VLM_API_KEY` and asks the registry like
   everyone else.
5. **Measure again.** Publish both numbers. If first-token regresses beyond the
   budget below, say so and reconsider rather than proceeding.

**Latency budget:** the extra hop is a loopback HTTP request. The added
first-token cost should be in the low tens of milliseconds. If it is over
~150 ms, the design is wrong and we look at a different seam — an in-process
adapter, or the agent importing `ProviderClient` directly rather than crossing
a socket.

**Done when:** voice, chat, mind and vision all appear in
`usage_by_provider()`, one cooldown stops all four, and the measured regression
is stated.

---

## Phase 13 — The harness seam

**Goal:** one Marvi. Today there are four personalities: `identity.compose()`
for chat, a string literal in `session.py` for voice, `SYSTEM_PROMPT` in
`deliberate.py`, and `PROMPT` in `describe.py`.

1. **`harness.py`** — one composer, `compose(task, surface) -> Prompt`.
   - **Resident** (always, every turn, byte-stable so it caches): SOUL.md,
     USER.md, the safety rules that must never be optional — untrusted content
     is information not instruction, confirmation before acting, the sleep rule.
   - **Task brief**: what varies. Voice gets "short sentences, no Markdown, the
     user can interrupt". Vision gets "describe this frame". Mind gets the
     decision framing.
   - **Volatile**: curiosity's question if one is due, plugin context lines,
     retrieved memory. Appended *after* the resident block so the cacheable
     prefix stays byte-identical — the property `chat.py` already relies on and
     the others do not have.
2. **Delete the three literals.** Each becomes a task brief.
3. **Voice gets the identity it has never had.** This is the "not idiotic, does
   not cold-start, follows the rules" requirement, and it is mostly this step:
   voice currently never sees SOUL.md or USER.md.
4. **Measure the resident block.** It is sent on every turn on the latency-
   critical path, so it has a token budget and a test that fails when it is
   exceeded. `identity.py` already has a budget mechanism; it becomes the whole
   harness's, not just the identity files'.

**Done when:** one composer, four callers, no personality string literals, and
a test asserting the resident block stays under budget.

---

## Phase 14 — Memory in the turn

**Goal:** Marvi walks into a conversation knowing what happened before. This is
the "no cold start" requirement, and it is a retrieval problem, not a prompt
problem.

The knowledge graph and the memory store exist and reach no prompt today.

1. **Retrieval before the turn.** Given the user's message (or the wake
   utterance), pull the few most relevant facts and recent episodes. Few is the
   point: a budget in items and tokens, enforced, because this is on the voice
   path.
2. **Graph-aware retrieval.** The knowledge graph is what makes "related things
   from past sessions" possible rather than keyword matching. One hop from the
   entities named in the turn.
3. **Where it goes.** Into the volatile section of the harness, after the
   cacheable prefix.
4. **Dreaming — the LLM in memory.** Consolidation and reflection are
   deterministic today (`reflect()` takes a `summarise` callable and every
   caller passes nothing). This phase gives them a model, running as a
   *scheduled auxiliary task*, not on the turn: read recent episodes, write
   durable facts, link entities in the graph, retire what is stale. It costs
   nothing at conversation time because it already happened.
5. **Latency rule:** retrieval is on the turn and must be bounded and measured;
   dreaming is off the turn and may take as long as it likes.

**Done when:** a fact learned on Monday reaches a Tuesday voice turn without
being asked for, the retrieval cost is measured and bounded, and consolidation
runs on a schedule with a model behind it.

---

## Phase 15 — Providers, models and effort

Now, and only now, the thing we originally set out to do — because each item
lands in exactly one place.

1. **Providers as documents** — `config/providers/<slug>.json`, one file per
   provider, loaded like `components.json`. Adding a provider is adding a file.
   One catalog behind every surface, with a parity test learned from the
   predecessor's provider catalog.
2. **`models.py`** — fetch the model list per `api_mode`, cached
   stale-while-revalidate. A failed fetch is reported, never replaced by a
   hardcoded list.
3. **`effort.py`** — the generic ladder, mapped per provider. Never
   `budget_tokens`. Omit rather than substitute.
4. **`ModelChoice`** — main, and per-task auxiliary slots defaulting to
   `auto` meaning "follow main". Marvi's own tasks: vision
   description, memory consolidation, chat titles, curiosity — the tasks the
   harness seam already names.
5. **The surfaces** — Providers page connect-only, Models page, session-only
   override in the composer.

Steps 1–4 are the engine and land together; step 5 is a separate release so a
break is attributable.

---

## What we are explicitly not doing yet

- Rewriting how LiveKit detects end-of-turn. It works and it is the hard part.
- Making memory retrieval clever before it is measured. A slow correct answer
  on the voice path is a wrong answer.
- Adding providers beyond the ones already in the registry, until the document
  format exists to add them to.

## The sequence, in one line each

- **12** — one place that makes a call.
- **13** — one thing that decides what Marvi says first.
- **14** — that thing knows what happened yesterday.
- **15** — and you can choose the model it uses.
