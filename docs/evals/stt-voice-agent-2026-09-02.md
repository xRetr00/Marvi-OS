# Streaming STT on the corpus that matches the job

Run on 2 September 2026 on the target Windows host: RTX 3060 12 GB, driver
610.88, Python 3.12. This round replaces
[stt-candidates-2026-09-01.md](stt-candidates-2026-09-01.md) as the basis for
which recogniser ships. That round is not wrong; it answered a different
question, and three of its measurements were taken through a harness that was
lying.

## Decision

**Parakeet TDT 0.6B v2 stays the default**, and now on evidence rather than on
incumbency: it wins accuracy, throughput and end-of-speech latency at once.

**Nemotron 3.5 and Kyutai STT 1B are both offered**, for two different reasons
that are not accuracy. Nemotron reaches a first partial 1.75 seconds sooner,
which is what subtitles are made of. Kyutai is the only recogniser here that
can say when the speaker has finished, and that is worth about 0.9 seconds of
turn-taking -- more than the gap between any two engines in the last column.

**WhisperLiveKit large-v3-turbo is rejected.** 6.2x realtime and the worst
accuracy in the round. It cannot be a live recogniser on this machine.

## Result

200 clips, 33 minutes, 4,864 reference words, from
`pipecat-ai/stt-benchmark-data`. One engine at a time, GPU to itself.

| Recogniser | WER | semantic WER | clean turns | RTF | first partial p50 | final after speech ends | empty |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Parakeet TDT 0.6B v2** | **3.44%** | **1.62%** | **71%** | **0.041** | 4,115 ms | **51 ms** | **0** |
| Nemotron 3.5 Streaming 0.6B | 7.30% | 4.38% | 52% | 0.380 | **2,364 ms** | 150 ms | 1 |
| Kyutai STT 1B | 8.10% | 5.55% | 56% | 0.420 | 3,618 ms | 472 ms | 1 |
| Whisper large-v3-turbo via WhisperLiveKit | 23.22% | 9.79% | 16% | 6.232 | 6,006 ms | 552 ms | 0 |

Whisper's semantic row is 199 clips; one reply the judge could not answer for
is recorded as `unjudged` rather than dropped.

### Semantic WER, and why it is here

Pipecat's metric: an LLM judge that ignores punctuation, capitalisation,
contractions, filler words and number formatting, and counts only errors that
change what was said. Every previous round in `docs/evals` used raw WER, which
charges two errors for "gonna" where the reference says "going to" and one for
"deploy the staging branch" where it says "destroy".

The two columns disagree most where it matters. Parakeet halves, 3.44% to
1.62% -- most of what raw WER charged it for was formatting. Whisper barely
moves, because its mistakes are the kind that alter meaning.

`clean turns` is the share of clips with no meaning-changing error at all, and
it separates these engines far harder than any average does: 71% against 16%.
One bad turn in four is a different assistant from one in twenty, and both can
average single-digit WER.

## Why this corpus and not the last one

EdAcc is two people in spontaneous cross-accent conversation, five seconds a
clip. L2-ARCTIC is read CMU prompts. Neither is somebody talking *to an
assistant*, and every ranking in the previous round was decided on the first.

The same Parakeet checkpoint scores 20.81% there and 3.44% here. It is not a
20% recogniser that got lucky; it is a 3% recogniser that was being asked the
wrong question. The accented numbers still matter and are kept below, because
"will it hear me" is a real question -- but it is a different one from "is this
the right recogniser for a desktop assistant".

| Recogniser | EdAcc WER | Arabic-accented WER |
| --- | ---: | ---: |
| Parakeet TDT 0.6B v2 | **20.81%** | **8.03%** |
| Nemotron 3.5 | 24.79% | — |
| Kyutai STT 1B | 35.26% | 20.17% |
| Whisper large-v3-turbo | 32.99% | — |

## Kyutai's semantic VAD

The reason to carry a recogniser that loses on every column above.

The 1B checkpoint has four extra prediction heads trained alongside the text,
each answering "has the speaker paused for N seconds" for N of 0.5, 1.0, 2.0
and 3.0 -- from content and intonation, not from silence. Every other
recogniser here is followed by a fixed 600 ms timer, which is wrong in both
directions: it cuts off someone thinking mid-sentence and makes everyone else
wait after an obviously complete question.

Measured over 14 voice-agent clips, threshold 0.5, counting every crossing:

| hold | head 1 (1.0 s) | head 2 (2.0 s) |
| --- | --- | --- |
| 1 frame | 8 premature, −0.44 s | 5 premature, −0.44 s |
| **3 frames** | 2 premature, −0.28 s | **1 premature, −0.28 s** |
| 5 frames | 1 premature, −0.12 s | 1 premature, −0.12 s |

Head 2 with a 240 ms hold: one false ending across fourteen clips, firing
0.28 s *before* the last word is transcribed. Head 2 is the 2.0-second head,
which is also what Kyutai ship in Unmute -- arrived at independently here.

What that buys, end to end, from the last word spoken to a final transcript:

    Parakeet   600 ms timer  +  51 ms flush   =  651 ms
    Kyutai    -280 ms VAD    + 472 ms flush   =  192 ms

Kyutai has the second-worst flush in the round and still reaches a final
transcript about 460 ms sooner than the winner, because it does not wait for a
timer. That is the trade: five points of semantic WER for half a second of
turn-taking, on every turn.

### The checkpoint

`kyutai/stt-1b-en_fr-candle`, not `kyutai/stt-1b-en_fr`. Same model, two
names, and only one carries the heads:

    stt-1b-en_fr          131 tensors, no extra_heads
    stt-1b-en_fr-candle   135 tensors, extra_heads.0..3.weight [6, 2048]

The previous round used the first and so measured this model with its one
distinguishing feature absent. A test now fails if the catalog points back at
it.

### Two guards, both load-bearing

The heads are pause detectors, so they are high through silence and spike for a
frame or two mid-utterance -- Kyutai's issue tracker records spikes past 0.99
on digit sequences. Without guards, the first probe of the real signal crossed
the threshold a second before the first word on every clip, and would have
ended one turn 8.9 seconds early.

* Nothing fires before the first word.
* The run must be unbroken for three frames.
* The 600 ms timer stays as a ceiling, so a VAD that never fires leaves
  behaviour exactly as it is today.

## Three harness faults found and fixed

Every one of these had already produced a number that went into a table.

**The CUDA clock was never synchronised.** The Kyutai runner timed how long it
took to *queue* work, not to do it. Measured three ways over 48 decodes: 24
ms/frame syncing never, 59.3 ms with one sync per clip, 78.7 ms syncing every
frame. The published RTF of 0.244 was the first of those and meant nothing.

**The benchmark started audio at the first syllable.** Fed audio that begins
mid-word, Kyutai emits nothing at all: six clips returned empty, and all six
transcribed correctly with one second of silence in front. Lead-in silence by
corpus -- EdAcc 0.02 s, L2-ARCTIC 0.07 s, Pipecat 0.98 s -- which is why the
problem was invisible until now, and why real voice-agent audio never triggers
it.

**The recogniser under test was decided by two environment variables.** With
neither set, `providers()` returns the processor and `chosen_model()` returns
the v3 multilingual model. A full 200-clip run completed that way, transcribed
beautifully, and reported RTF 0.539 against the recorded 0.055 -- a different
model on a different device, in a row that looked like all the others. The
runner now refuses to run on the processor without `--allow-cpu`.

Two scoring faults were fixed alongside: `stt_score.py` required an `l1` field
that a corpus without a first-language dimension does not have, and the
semantic judge took a greedy `{.*}` match that broke on a reply containing two
JSON objects -- after 200 clips had already been transcribed.

## Reproducing

```
python evals/pipecat_corpus.py <destination> --limit 200
pwsh evals/pipecat_round.ps1
python evals/kyutai_vad_probe.py <manifest> <corpus> <model> --hold 3
```

`pipecat_round.ps1` sets `MARVI_STT_DEVICE=cuda` and `MARVI_STT_LANGUAGE=en`
and runs one engine at a time; both matter, and the first round of this
benchmark got both wrong.
