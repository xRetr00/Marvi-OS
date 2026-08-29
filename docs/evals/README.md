# Evals and benchmarks

How Marvi decides whether a model, a tool, or a small local model is good
enough to ship. One method, applied to seven different kinds of component.

Everything here follows from one rule:

> **Every case is a failure that actually happened.**

Not a public benchmark, not a capability score, not a vibe. A case earns its
place in a suite by being something Marvi got wrong in front of her owner, with
the log line to prove it. That is what makes a passing score mean "would not
have produced that conversation" rather than "scored well on someone else's
test set".

## Why not standard benchmarks

Marvi is a voice assistant that runs continuously on one machine for one
person. Nothing in MMLU or LMArena predicts whether a model will read its own
system prompt out loud when a memory block gets long, and that is the failure
that actually made her unusable. A model can be excellent and wrong for this.

The corollary matters too: **a model that wins here has not been shown to be
better in general.** These suites answer one question — is this component right
for Marvi — and refuse the temptation to answer any other.

## The ranking, and it is not negotiable

The owner set it: **behaviour, then latency, then cost.**

A model that is fast and cheap and leaks the prompt is not a cheaper option,
it is a broken assistant. Latency is a tiebreak between models that behave, and
price is a tiebreak between models that behave *and* are fast. A suite that
reports a single blended score hides exactly the trade the ranking exists to
prevent, so the tables here keep the three columns apart and sort by the first.

## What exists today

| Suite | What it decides | Run it |
| --- | --- | --- |
| [Voice model behaviour](voice-models.md) | Which LLM answers spoken turns | `python evals/voice_behaviour.py` |
| [Memory reader](memory-reader.md) | Whether memory needs a model to read it | `python evals/memory_answers.py` |
| [Retrieval quality](retrieval.md) | Embedding model, thresholds, recall shape | see the doc |
| [Speech](speech.md) | STT model and lookahead, TTS voice | see the doc |
| [Tools](tools.md) | Whether a tool is callable, safe, and worth its schema | see the doc |
| [From life](from-life.md) | The same failures, scored against real use | `python evals/from_life.py` |

## The method, in six steps

Every suite in this folder is built the same way.

### 1. Start from a real failure, not a capability

Read the logs. Find the turn where Marvi did the wrong thing. Quote it into the
case as a comment, verbatim, with the date. If you cannot point at a real
occurrence, you are writing a benchmark, not an eval — and it will pass
forever while the real problem continues.

### 2. Establish the base rate before you change anything

Run the suite against what is shipping now. Without that number, an improvement
is a feeling. Several changes in this project were abandoned at this step
because the thing they were meant to fix scored the same before and after: a
bigger bi-encoder, two cross-encoder rerankers, MMR diversification, and a
quantisation pin were all measured and none of them moved the number.

### 3. Make the check assert the behaviour, not the wording

A check that greps for a phrase will pass a model that says the same wrong
thing differently, and fail a model that says the right thing in unexpected
words. Both happened here:

- The leak check originally matched `"untrusted"`. A model correctly reporting
  *"an untrusted email asked me to turn the light off"* was scored as leaking —
  the check punished the exact behaviour the neighbouring case was testing for.
- The tool cases assert *which tool was called*, which no amount of rewording
  can fake.

Prefer an assertion over a structural fact (a tool call, a length, an absence)
to one over prose.

### 4. Separate "failed" from "did not answer"

A 429, a 403, a timeout, a model that requires terms you have not accepted —
none of these are behaviour. Scoring them as failures made two good models look
broken in the first run of the voice suite: qwen scored 2/3 on brevity and ling
0/3 on tool choice, and both were 4/4 on a rerun minutes later. Count errors in
their own column and score each case out of what actually returned.

### 5. Run it more than once

Sampling is not deterministic. Three runs per case is the floor and four is
better; a 1-in-4 failure is a real finding and a 1-in-1 is noise. Report the
fraction, never a bare pass/fail.

### 6. Write down what you disproved

The most valuable output of an eval is often a killed hypothesis. `docs/` and
the source comments in this project carry several, each one saving somebody
from re-running the same experiment. A suite that only ever records wins is
being used to justify decisions rather than to make them.

## What this does not measure

Worth stating so nobody mistakes a green suite for a working assistant:

- **Nothing here is a live conversation.** Every case is a single scripted
  turn. Turn-taking, interruption, and how a model behaves in the ninth minute
  of a session are not covered.
- **Latency here is API round-trip**, not end-to-end. What a person feels also
  includes STT settle, endpointing, TTS time-to-first-byte and playback. Those
  are recorded live and read back through `GET /latency`, not here.
- **Cost is per turn at one prompt size.** Real cost depends on how the context
  grows over a session, which these do not simulate.

## The suites that grow by themselves

Everything above is scripted: somebody wrote the case, and it is frozen at the
moment they wrote it. `evals/from_life.py` is the other half. Marvi records
what she does as she does it -- recalls, store decisions, gate decisions, tool
calls and spoken replies -- and that suite scores the same failures against
real use.

The point is the rule at the top of this file, made automatic. A case earns its
place by being something Marvi got wrong; the recorder is what makes "something
Marvi got wrong" findable without a person grepping four log files. When
`from_life` reports a leak or a missing tool, that is not a prediction -- it
happened, in a conversation, and the row is there.

Read it after a week of real use, not after an hour. Its most valuable output
is the one no scripted suite can produce: **which tools Marvi reached for and
did not have.**

## Adding a suite

Put the runnable harness in `evals/`, the reasoning and the results table in
`docs/evals/`. The harness's module docstring should say where each case came
from; the doc should say what was decided and what was rejected. Keep them
together — a result with no method is unrepeatable, and a method with no result
is untested.
