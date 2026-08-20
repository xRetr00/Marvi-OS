# Real Streaming

**Status:** planned, not started
**Depends on:** the provider seam (done), `/llm` SSE (exists, unused)

Marvi does not stream. Chat waits for the whole reply and then prints it, and
the voice path waits for the whole reply before the first word is spoken. Both
are the same missing thing, and the second one is the expensive one: a spoken
turn is judged almost entirely on how long the silence lasts before Marvi
starts talking, and right now that silence is the model's entire generation
time.

This is the plan for fixing it properly, once.

## Why it is not just a UI change

The obvious framing — "make the chat bubble type out" — is the wrong one. Text
appearing gradually in a box is a rendering detail. The thing worth building is
that **the first token leaves the provider and reaches its consumer without
waiting for the last one**, and that has to be true through four layers before
any animation matters:

```
provider  →  ProviderClient.stream()  →  Gateway  →  consumer
                                                     ├─ chat  (SSE → renderer)
                                                     └─ voice (chunks → TTS)
```

`ProviderClient.stream()` already exists and yields `{"delta": str}` then
`{"done": True, "usage": {...}}`. `/llm` already serves SSE. Neither has a
caller. Chat uses the blocking `call_with_fallback`; voice uses the LiveKit
plugin's own path and never touches either.

So the work is not "add streaming" — it is "connect the streaming that is
already there, and deal with everything that assumed it was not".

## What makes this hard

Four things, and none of them are the SSE.

**Tools.** Chat's loop calls the model, inspects `tool_calls`, dispatches, and
calls again. A streamed response does not have tool calls until it is finished,
so the loop either buffers (and streams nothing on any turn that uses a tool)
or it streams text and tool calls separately and reconciles them. The second is
correct and is most of the work. Note that a turn which ends in a tool call has
no user-visible text to stream anyway — the streaming case and the tool case
are nearly disjoint, which is the thing that makes an incremental version
possible.

**Fallback.** `call_with_fallback` tries providers in order until one answers.
Once bytes have been sent to the client, falling back is no longer transparent:
the user has already seen half a sentence from a provider that then died. The
rule has to be that fallback happens **before the first delta** and is a hard
error after it — which means the stream cannot be handed to the client until
the first token arrives.

**Cancellation.** A streamed turn can be abandoned: the user closes the window,
sends another message, or interrupts Marvi mid-sentence. Today nothing can be
cancelled because nothing is in flight long enough to matter. Every layer needs
to propagate a cancel, and the provider connection needs to actually close —
an abandoned stream that keeps generating is billed in full.

**Reasoning.** Reasoning tokens arrive interleaved with content and must not be
spoken, must not be sent to the TTS, and should be shown separately in chat
(collapsed by default). Each API marks them differently: OpenRouter sends
`reasoning` deltas, the Responses API sends reasoning items, Anthropic sends
`thinking` blocks. `read_stream_line` already knows the three envelopes; it
needs to classify rather than concatenate.

## Phases

Each phase is shippable on its own and leaves Marvi working.

### Phase A — chat streams text

`/chat` gains an SSE variant. The tool loop keeps its blocking call for any
round that returns tool calls; the **final** round — the one that produces
prose — streams. That is where all the visible latency is, and it sidesteps the
tool reconciliation entirely for the first cut.

- `POST /chat/stream` → SSE of `{delta}` / `{tool}` / `{done, usage}`
- Renderer consumes it and appends into the live message
- Fallback resolved before the first delta; error after it ends the turn
- `first_token_ms` becomes real for chat, so `/latency` finally compares like
  with like against voice

**Done when:** a chat reply appears word by word, `/latency` shows a chat
first-token figure, and a turn that calls tools still works exactly as now.

### Phase B — reasoning is separated and shown

- `read_stream_line` classifies each delta as `content` or `reasoning`
- Reasoning is never spoken and never sent to TTS
- Chat renders it in a collapsed block above the answer, with its own token
  count, because reasoning is most of the bill on a thinking model and
  invisible cost is the kind people get angry about

**Done when:** a reasoning model shows its thinking separately and the spoken
path is unaffected.

### Phase C — voice speaks from the stream

The one that matters. Today the agent's LLM returns a complete reply and only
then does the TTS begin. Instead:

- The agent's LLM adapter yields deltas as they arrive
- A sentence tokenizer batches them into speakable units (`StreamAdapter`
  already does this; it is being fed too late, not incorrectly)
- The first sentence goes to the TTS while the rest is still generating

The budget from the Phase 12 plan applies here: **first-token latency must not
regress by more than 150 ms** against the direct path, measured by the
comparison that now actually records samples.

**Done when:** `latency compare` shows voice first-token improved by roughly
the model's generation time for a sentence, and no worse on any measure.

### Phase D — cancellation

- Interrupting Marvi closes the provider connection rather than draining it
- A new message supersedes an in-flight one
- Closing the window cancels

**Done when:** interrupting mid-sentence stops billing, verifiable in the usage
counter.

## What "done" is not

- Not a typewriter animation on a complete string. That is the thing to avoid;
  it looks like streaming and fixes nothing.
- Not streaming only in chat. Chat is where it is easiest to see and voice is
  where it is worth having.
- Not a second code path. The same `ProviderClient.stream()` serves both
  consumers, or the two will drift and only one will get fixed.

## Open questions

- Does the LiveKit plugin's `LLMStream` interface let the agent yield partial
  content, or does the `GatewayLLM` seam need to own the whole path? The seam
  exists and is unused; this decides whether it gets switched on.
- Should chat history store reasoning? It is useful for a follow-up and
  expensive to replay. Leaning towards storing but not replaying.
- Per-provider streaming quirks are unknown until tried; OpenRouter is the only
  one confirmed to stream cleanly with usage included.

## Reference

The UI shape the user asked for is a word-by-word reveal with a cursor and a
brief highlight on the freshest words — the `StreamingText` component pattern,
where the animation is driven by a growing token count rather than by a timer.
That is Phase A's renderer, and it only works if the count grows because
tokens actually arrived.
