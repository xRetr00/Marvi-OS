# Speech: recognition and synthesis

The two components a person judges before Marvi has said anything useful.

## Recognition

Parakeet TDT 0.6B through a streaming ONNX wrapper. Two model choices and one
setting — and the setting matters more than the choice.

### The language lock is the model, not the prompt

v3 recognises twenty-five languages and takes no argument to narrow that; it
detects the language itself. An accented sentence comes back as another
language, and the model then answers in it. Real transcripts from this
installation include `Эй, Морви.` and `Ньюкс.` — Cyrillic, from English speech.

v2 has no other language in its vocabulary and cannot make that mistake. A
prompt saying "reply in English" is one sentence against a whole visible
conversation, and it loses. **The recogniser is the lock.**

### Lookahead: the one real trade

| lookahead | word error | held audio |
| --- | --- | --- |
| 2.0 s | 13.7% | up to 2.0 s |
| 0.8 s | 16.8% | up to ~1.2 s |

The accuracy figures come from a corpus run. The latency half was established
from live logs and is the more important half:

- `transcript behind` median 198 ms, **p90 2,930 ms**
- `end of turn` tracks it within ~380 ms at both median and p90
- the flush itself is only 190 ms median

So the tail is not the flush. At flush time there is up to a full lookahead of
undecoded audio, and a *short* utterance lives entirely inside that buffer — it
produces no text at all until the flush. Long utterances decode as they go and
never show the problem, which is why this looked intermittent for so long.

**How to measure a change:** compare `transcript behind` percentiles before and
after, splitting on the `parakeet ready in Xs on cuda, Ys lookahead` line that
marks each session. Judge on the p90, never the median — the median was already
healthy at both settings, which is exactly why the problem survived.

### Word accuracy on names

Proper nouns are corrected after recognition rather than by the model:
`vocabulary.correct` matches against names from the memory graph
(`CLOSE_ENOUGH = 0.60`, first-letter gate, length ratio ≥ 0.7). "NeuDocs" was
heard as "New Ducks", "new dogs N E" and "New." — and a name misheard is a name
re-remembered, five times over.

## Synthesis

Kokoro-82M, English only. Measured live: `tts ttfb` 346 ms median, 612 ms p90,
generation at 8–13× real time.

Six newer streaming candidates were screened and three were run on the target
RTX 3060 on 31 August 2026. None replaces Kokoro yet. CuteTTS-distill,
VoXtream2, and CTC-TTS-F are selectable experimental isolated runtimes at the
owner's direction; CTC still lacks a completed native-Windows synthesis run.
VoxCPM2 fails realtime/VRAM gates, while Breeze-TTS-2.cpp and Gepard remain
outside the supported native-Windows path. The
revisions, raw timings, intelligibility smoke test, and exact failures are in
[the candidate report](tts-candidates-2026-08-31.md).

Two things worth knowing:

- **English-only is a constraint on the whole system**, not a preference. It is
  stated in the persona so Marvi does not offer a language she cannot
  pronounce.
- **Synthesis shares one GPU with recognition.** `inference is slower than
  realtime` and `job executor is unresponsive` appear near 14% of slow turns
  and 0% of fast ones. Anything that makes either model heavier is paid twice.

## Reply length

Not a model property but measured here because it is heard as one:
`VOICE_REPLY_TOKENS = 250` permits **67.8 seconds** of speech, measured. The
persona asks for short sentences. When those two disagree the cap wins, and a
listener hears a monologue. Any change to either number should be checked
against real audio duration, not token count.

## What is not measured here

Naturalness, prosody, and whether a voice is pleasant to listen to. Those are
judged by listening, and no number in this folder substitutes for that.
