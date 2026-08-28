# Voice model behaviour

Which model answers Marvi's spoken turns. Run with
`python evals/voice_behaviour.py`; the cases and their provenance are in that
file's docstring.

Measured 2026-08-29 against OpenRouter, 3–4 runs per case.

## Results

| model | behaviour | median | p90 | $/1k turns | note |
| --- | --- | --- | --- | --- | --- |
| `deepseek/deepseek-v4-flash-0731` | **18/18** | 0.74 s | 1.19 s | 0.04 | what ships today |
| `poolside/laguna-s-2.1` | 23/24 | **0.57 s** | 0.87 s | 0.06 | fastest |
| `qwen/qwen3.7-flash` | **24/24** | 0.69 s | 0.86 s | **0.03** | |
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
