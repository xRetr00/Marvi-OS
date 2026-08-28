# Retrieval quality

Whether Marvi finds the memory that answers the question. This is the suite
with the most disproven hypotheses in it, and they are the point.

## The case that drives it

    ? what is my schedule like
      - The user uses deepseek-v4-flash for scheduled cron jobs
      - The user routes cron job output to a Telegram channel

The answer — *works as the main dough chef at a bakery in Düzce, typically
night shifts* — was in the store and ranked nowhere. It is a schedule and never
says so.

## Method

Eight questions, each with the substring that proves the right memory surfaced,
run against a **copy** of the real store so a measurement never changes the
thing being measured. Score is how many find it in the top five.

## What was tried and rejected

Every one of these was implemented, measured, and removed:

| Change | Result |
| --- | --- |
| Larger bi-encoder | same score |
| Cross-encoder reranker (two different ones) | same or worse |
| MMR diversification | worse |
| Question-vocabulary line appended before embedding | enriched 128/144 correctly, **score did not move** |

The last is the most instructive. The enrichment worked — the bakery memory was
given "work, job, employment, night shift, schedule", exactly the missing word
— and the score stayed at 7/8. The retrieval line was concatenated to the
memory and the pair embedded as one text, so eight keywords sat beside a
sentence four times their length and moved the vector very little. The fix
would be a *second vector* scored independently: a schema change, not yet done.
See `rephrasing.py`.

## What did change something

**Nothing about ranking. The confidence signal.** Measured over the real store:

| query | top score | right answer? |
| --- | --- | --- |
| what computer do I have | 0.657 | yes |
| what do I do for work | 0.638 | no — the right one is 4th at 0.550 |
| who am I | 0.590 | partly |
| what is my schedule like | 0.562 | no, and nothing below it is either |

A question the store can answer tops out around 0.64–0.66; one it cannot tops
out at 0.562. So the *top* score separates "found something" from "returned
five things anyway" — and nothing else does, because within one result set the
scores sit inside a 0.1 band.

`recall_block` now weakens its heading when the best match is poor, and drops
nothing. A relative gate sized to this data would have deleted the bakery
memory, which is the correct answer to one of the eight questions.

## The threshold that is not about retrieval at all

Recall blocks over roughly 1,600 characters make the model continue the prompt
instead of answering it: over one real session, 0 of 19 turns under that length
leaked instructions into speech and 3 of 7 over it did. `BLOCK_CHARS` bounds
the whole block for that reason, not for cost.

## Embedding model

`BAAI/bge-small-en-v1.5`, 384 dimensions, local, chosen over MiniLM on
asymmetric-retrieval testing (ADR-026).

Changing it invalidates every stored vector. `search_similar` filters on
`(model, dimension)`, so a changed model matches **zero rows** — semantic
search dies silently while keyword search covers for it, and the only symptom
is worse answers. Any change here must re-embed the store, and the eight
questions are how you tell whether it was worth it.
