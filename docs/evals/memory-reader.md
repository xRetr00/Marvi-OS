# Does memory need a model to read it?

Marvi's memory had four model passes on the **write** side and none on the
read side. This is the measurement that decided whether to add one, and what
*not* to build as a result.

Run with `python evals/memory_answers.py`. Measured 2026-08-29 against the real
store of 153 memories, reader `qwen/qwen3.7-flash`, 2 runs per question.

## Results

Eight questions the store can answer, two it cannot.

| condition | right of 8 | abstained of 2 | median | $/1k recalls |
| --- | --- | --- | --- | --- |
| `search_top1` | 4 | 0 | 30 ms | 0.00 |
| `search_top5` | **8** | 0 | 30 ms | 0.00 |
| `read_5` | **8** | **2** | 635 ms | 0.01 |
| `read_10` | **8** | **2** | 621 ms | 0.02 |

## What this settles

**Retrieval does not need improving.** Every answerable question had its answer
inside the top five. The embedder finds it.

**Ranking is bad, and fixing it is the wrong project.** Top-1 was right half
the time — asked *"what do I do for work"*, the bakery memory came back fourth
at 0.550, below three higher-scoring wrong ones. That is a real defect and it
is also already solved by handing the model five rows instead of one. Four
ranking improvements have been measured on this store and moved nothing (a
larger bi-encoder, two cross-encoders, MMR); a fifth would move top-1 and
change no answer.

**The thing search cannot do is say "I do not know."** It returns five rows
whatever it is asked. Both unanswerable questions were answered confidently
from unrelated rows under `search_*`, and abstained on correctly under
`read_*`, in every run. This is the root of the confabulations in the logs:
asked about a schedule with nothing in the store about one, Marvi was handed
five confident lines about cron jobs and answered from them.

## Answers to the questions this was run to settle

**Do we need a reranker?** No. It would improve the one number (top-1) that
stops mattering once a reader exists.

**A classifier?** No. The reader's abstention *is* the classifier, and it
classifies with the memories in front of it rather than the query alone.

**A vector database or an index?** No. 153 vectors, linear scan, 27.6 ms. An
index earns its complexity somewhere north of 100,000 vectors; this store would
need to grow by three orders of magnitude. Revisit then, not before.

**Is the embedding used?** Yes, and it is doing its job — see the first
finding. Keyword search runs only on lookups, not on questions, for reasons
measured separately (`retrieval.md`).

## Where it runs, and why that is free

The reader costs ~600 ms, which is roughly the whole `llm ttft` of a spoken
turn. Put on the critical path it would double the wait before Marvi speaks.

It is not on the critical path. The voice worker already fetches recall
speculatively while the user is still talking, and over 121 real turns that
window is **1,789 ms at the median and 1,082 ms at the lower quartile — a
635 ms reader fits inside 98% of them.**

So `/memory/recall?read=1` is requested by the prefetch only. The live
fallback, which runs when the prefetch missed and the turn is already waiting,
asks for the plain memory list exactly as before. A reader that is slow simply
does not arrive in time to be used; nothing waits for it, and there is no
timeout to tune.

## What is kept alongside the answer

The reader's answer goes *above* the memory list, not instead of it. Marvi has
to be correctable — *"no, the other one"* needs the other one to still be
visible — so the answer is presented as what she has worked out and the
memories stay underneath as what she worked it out from.

## How to re-run this after changing anything

    python evals/memory_answers.py --runs 3 --model <candidate>

Watch two columns, not one. A reader that scores 8/8 and abstains 0/2 is worse
than the search it replaced: it has learned to always answer, which is the
failure this was built to stop.

## What this does not measure

- **Whether the answer is worded well.** Only whether it contains the fact.
- **Multi-turn behaviour.** Every question here is asked cold. Whether the
  reader helps or hurts when the conversation already carries the context is
  untested.
- **A store ten times this size.** Both the linear scan and the reader's
  ability to pick from a wider set will change, and neither has been measured
  past 153 memories.
