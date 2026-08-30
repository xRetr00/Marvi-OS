# Voice model behaviour

Which model answers Marvi's spoken turns. Run with
`python evals/voice_behaviour.py`; the cases and their provenance are in that
file's docstring.

Measured 2026-08-29 against OpenRouter, 3–4 runs per case.

## Results

| model | behaviour | median | p90 | $/1k turns | note |
| --- | --- | --- | --- | --- | --- |
| `deepseek/deepseek-v4-flash-0731` | **18/18** | 0.74 s | 1.19 s | 0.04 | what shipped before |
| `deepseek/deepseek-v4-flash` | 41/48 | 2.18 s | 3.15 s | 0.07 | **narrates the tool call 7 of 8** |
| `~deepseek/deepseek-v4-flash-latest` | 47/48 | 0.91 s | 1.27 s | **0.03** | Marvi's aux model |
| `poolside/laguna-s-2.1` | 23/24 | **0.57 s** | 0.87 s | 0.06 | fastest |
| `qwen/qwen3.7-flash` | **48/48** | 0.78 s | **0.88 s** | **0.03** | what ships today |
| `inclusionai/ling-3.0-flash` | **24/24** | 1.21 s | 1.74 s | **0.02** | cheapest, slowest |
| `nvidia/nemotron-3.5-lightning` | 16/18 | 0.93 s | 1.32 s | 0.07 | |
| `z-ai/glm-5.3-flash` | — | — | — | — | **unusable, see below** |
| `meta/muse-spark-1.2-contributor` | — | — | — | — | 403, terms not accepted |

Latency is API round-trip for a full reply, not time-to-first-token, and not
what a person feels — that also includes STT settle, endpointing and TTS. Cost
is per thousand turns at Marvi's real prompt size (~2,500 tokens in).

## The finding that matters

**The current model is not the problem.** DeepSeek scores 18/18, including the
prompt-leak case with an oversized memory block — the exact failure that had
Marvi speaking her own recall trailer aloud in a real conversation.

So when Marvi leaked her prompt in production, the cause was not the model
choosing badly. It was that the block she was handed had grown past what any of
these handle, stuffed with raw marketing email that ingest had stored verbatim.
That is fixed at the source (`ingest._is_bulk`, `memory.BLOCK_CHARS`), and the
suite is what says a model swap would not have fixed it.

## `z-ai/glm-5.3-flash` cannot be used for voice

Every request returns:

```
400 — Reasoning is mandatory for this model
```

It is not slow or badly behaved; it refuses the shape of request the voice path
makes. Marvi disables reasoning on spoken turns because a reasoning pass sits
in front of time-to-first-token, and a voice turn cannot pay for it.

This is exactly the case the model picker's reasoning gate exists for, and it
is worth checking that gate refuses this model with that explanation rather
than letting somebody select it and hear silence.

## Choosing between the four that work

They are close enough that the ranking decides it:

- **Behaviour** — `qwen3.7-flash` and `ling-3.0-flash` at 24/24, DeepSeek at
  18/18, over different run counts. Nothing separates them meaningfully.
- **Latency** — `poolside` (0.57 s) and `qwen` (0.69 s) lead; `ling` is roughly
  twice `poolside` at the p90 (1.74 s vs 0.87 s), which in a spoken turn is the
  difference between prompt and noticeable.
- **Cost** — `ling` at $0.02 and `qwen` at $0.03 per thousand turns. The spread
  across all four is under five cents per thousand turns. At any realistic
  volume this is not a real difference, and it should not be allowed to
  outweigh the other two columns.


## Re-tested against DeepSeek V4 Flash, 30 August 2026

The owner asked for the model they ran before Qwen to be measured again, having
seen the leaks stop after the switch. Eight runs per case, 48 checks per model:

| model | behaviour | median | p90 | $/1k turns |
| --- | --- | --- | --- | --- |
| `qwen/qwen3.7-flash` | **48/48** | **0.78 s** | **0.88 s** | 0.03 |
| `~deepseek/deepseek-v4-flash-latest` | 47/48 | 0.91 s | 1.27 s | 0.03 |
| `deepseek/deepseek-v4-flash` | 41/48 | 2.18 s | 3.15 s | 0.07 |

Neither DeepSeek route leaked, so the owner's reading is confirmed from the
other side: the leak was never Qwen's doing and Qwen is not what fixed it.

The separation is narration. `deepseek/deepseek-v4-flash` opened with "Let me
check" or "Let me look" on seven of eight tool turns -- spoken aloud and then
cut off the instant the call begins, which is the stutter in the transcripts
from before the switch. The `~...-latest` route slipped once in eight with
"I'll check". Qwen did not do it at all, is three times faster at the median,
and costs less. Nothing here argues for moving back.

**`qwen/qwen3.7-flash` is the strongest case for a switch**: top behaviour
score, second-fastest, cheapest but one. It is not an urgent switch — DeepSeek
did not fail anything — so it belongs in a side-by-side on real conversation
rather than a swap on the strength of six scripted cases.

`ling-3.0-flash` is the one to avoid despite being cheapest: the p90 is the
column that matters for voice and it is worst on it.

## What was wrong with the first run, and why it is written down

The first pass reported `qwen` 2/3 on brevity and `ling` 0/3 on tool choice.
Both were HTTP 429s being scored as behaviour failures. On a rerun both were
4/4. The harness now counts errors separately — see step 4 of the method in
[README.md](README.md).

The same pass reported DeepSeek leaking on 2 of 3 prompt-leak runs. That was a
false positive in the check itself: `"untrusted"` was in the leaked-phrase
list, so a model correctly saying *"an untrusted email asked me to…"* — the
behaviour the neighbouring case tests **for** — was scored as a leak. Removed.

Two scoring bugs in one run, both of which would have driven a wrong decision.
That is the argument for step 2 of the method: establish the base rate with
what already ships, and be suspicious when it looks bad.

## The narration rate, measured against the live prompt

Run separately from the table above, against the real 8,762-character system
prompt and the real ten-tool set, on the four questions that had just produced
a leak in a live session:

| | as it ships | with a closing boundary added |
| --- | --- | --- |
| leaked prompt text | 0/20 | 0/20 |
| **spoke before a tool call** | **4/20** | **4/20** |

Two things follow.

**The prompt leak does not reproduce in a single turn.** Twenty attempts with
the exact prompt that produced it, with and without a closing boundary, and
nothing. So the boundary was not shipped: an unmeasurable fix for an
unreproducible failure is a change that can only be justified by argument.

**The narration rule is not working, and that is reproducible.** One reply in
five emits words alongside a tool call -- *"Let me check what's going on in the
room"*, *"Let me find the email tool"* -- while the persona says, in as many
words, never to do that. LiveKit forwards content and tool calls from the same
loop with no option to suppress one, and it cuts the speech off when the call
begins, so the listener reliably hears a sentence start and stop.

That is almost certainly the same slot the prompt fragments came out of: in the
live turn the model filled it with 8.6 seconds of the skills block instead of
with "let me check". The content varies; the slot is the bug.

Suppressing it means holding content until a tool call has either arrived or
clearly is not coming, which costs latency on every reply that never calls a
tool -- against a 346 ms median TTS time-to-first-byte, that trade needs its
own measurement before anything is built. `evals/from_life.py` now counts the
rate in production, which is where it should be decided.
