# Streaming STT challengers: accented-English bakeoff

Run on 1 September 2026 on the target Windows host: RTX 3060 12 GB,
driver 610.88, Python 3.12, and Rust 1.94.1. This is an accented-English
benchmark first. It is not a clean-American-English model-card comparison.

## Decision

**No candidate is promoted.** The Qwen Rust rolling implementation is the
accuracy leader at 20.23% WER, but its available native-Windows CPU path is
slower than realtime and takes 3.76 seconds to produce a first partial.
Nemotron 3.5 is the best GPU compromise at 30.06% WER and 0.099 RTF, but its
1.06-second first useful partial still misses Marvi's 300 ms median gate.

The current Parakeet TDT recognizer remains the non-streaming baseline
exception. Its historical 13.7% figure used an earlier corpus and must not be
compared numerically with this pinned slice. None of these results authorizes a
default change or claims completion of speaker-loop, interruption, or soak
acceptance.

## Result

Sorted by accented-English accuracy, then checked against realtime behavior.
VRAM is incremental above the desktop baseline.

| Candidate and native path | Streaming behavior exercised | WER | RTF | first partial p50 / p90 | final after EOS p50 | peak RAM | peak VRAM | Result |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Qwen3-ASR 0.6B `qwen3-asr-rs` | rolling 8 s window, prefix rollback, CPU f32 | **20.23%** | 1.462 | 3,762 / 4,363 ms | 2,515 ms | 3,044 MB | CPU | reject: not realtime |
| Nemotron 3.5 Streaming 0.6B | cache-aware RNNT, 320 ms feeds, CUDA f16 | 30.06% | **0.099** | 1,065 / 2,753 ms | 33 ms | 2,736 MB | 2,967 MB | best GPU challenger; partial gate failed |
| Parakeet Realtime EOU 120M | cache-aware RNNT, 160 ms feeds, CUDA f16 | 34.46% | 0.125 | **903 / 2,178 ms** | **20 ms** | 3,222 MB | **2,187 MB** | reject: accuracy and partial gate |
| Qwen3-ASR 0.6B causal | append-only causal tower, 1.92 s blocks, CUDA bf16 | 37.98% | 0.437 | 7,991 / 10,953 ms | 696 ms | **2,124 MB** | 5,762 MB | reject: accuracy and latency |
| Qwen3-ASR 0.6B official vLLM realtime | official rolling/prefix-stabilized server | — | — | — | — | — | — | ineligible: vLLM has no native Windows support |

The first-partial value is when a useful non-empty partial becomes available:
audio presented to that point plus synchronous inference time. RTF and EOS
latency measure model work, not microphone endpointing or LiveKit transport.

## Accuracy by first-language background

WER is aggregate word error within each six-clip group. `Ghanain English` is
the spelling in the pinned EdAcc metadata and is retained for reproducibility.

| L1 group | Qwen Rust rolling | Nemotron 3.5 | Parakeet EOU | Qwen causal |
| --- | ---: | ---: | ---: | ---: |
| Ghanain English | **8.00%** | 17.33% | 24.00% | 25.33% |
| Hindi | **7.55%** | 9.43% | 11.32% | 15.09% |
| Indian English | **13.68%** | 16.84% | 25.26% | 23.16% |
| Jamaican English | **20.90%** | 26.87% | 31.34% | 32.84% |
| Kenyan English | **22.86%** | 44.29% | 54.29% | 52.86% |
| Lithuanian | **20.69%** | 27.59% | 37.93% | 36.78% |
| Mandarin | **17.98%** | 26.97% | 25.84% | 28.09% |
| Nigerian English | **28.99%** | 50.72% | 57.97% | 73.91% |
| Spanish | **40.26%** | 50.65% | 41.56% | 55.84% |

Normal English would have hidden the main finding. Kenyan, Nigerian, and
Spanish-accented speech separate these engines sharply; the small EOU model's
speed does not compensate for losing more than half the words in two groups.

## Corpus and scoring protocol

- Source: EdAcc test split, pinned revision
  `d9ae7bd344f0562b766ec93ee5ce8f2f9568ce66`.
- 54 spontaneous-conversation clips: six clips from nine L1 backgrounds,
  248.190 seconds, 682 normalized reference words, and 20 speakers.
- The first 7,300 test rows form the pinned selection pool. Rows are ranked by
  a stable hash, capped at three clips per speaker on the first pass, limited to
  5–28 words and 1.5–12 seconds, then converted to mono 16 kHz signed PCM.
- Reference and hypothesis receive the same NFKC/case-fold transform. EdAcc
  non-speech tags are removed; punctuation is not scored. WER is total
  substitutions + deletions + insertions divided by total reference words,
  never a mean of clip percentages.
- Every model is loaded once, warmed where supported, and receives fresh stream
  state for every clip. No whole-utterance transcription result is substituted
  for streaming events.

Manifest SHA-256:
`B809D38ACB41DC5B07B680393BA978858A069FA6239D1C722A50143BF9017B77`.
The complete local predictions remain under
`%LOCALAPPDATA%\Marvi-OS\evals\stt-candidates\results`; their hashes and compact
metrics are checked into `evidence/stt-2026-09-01/summary.json`.

## Exact upstreams exercised

- Qwen base model `Qwen/Qwen3-ASR-0.6B`
  `5eb144179a02acc5e5ba31e748d22b0cf3e303b0`.
- Causal runtime `QuentinFuxa/Qwen3-ASR-causal`
  `89752586ca978d72773732422b81bf03eea2e5e2` and causal tower
  `qfuxa/qwen3-asr-0.6b-streaming`
  `827e7ae1d4212cf3080440da728b4d063fd2eef1`.
- Official Qwen runtime `QwenLM/Qwen3-ASR`
  `7c6daf77a2421100f5fb066495372c00129d39ff`.
- Rust rolling runtime `lumosimmo/qwen3-asr-rs`
  `7984967e8701cc90bb17d06453901036e36ca578`.
- `parakeet.cpp` v0.5.0 official Windows CUDA binaries and f16 GGUFs from
  `mudler/parakeet-cpp-gguf`
  `bf0af9f425fa01809cadec671b3cb672709d13e9`.

The downloaded v0.5.0 archives were also pinned by SHA-256: CLI
`0C90F619A368E67418596231470E916FDA60118180879E4334D29D9B0DF93B21`, CUDA
runtime `CC2B5FB99951720130E4A701E0978419D0A878E25C88BEBC1416152616BD1D94`, and
C ABI library
`BE61348D3E1EA60059C141AE3EDA7F04BD69BEA80ECC689F96BC47A6A1691016`.

The Rust crate supports Candle CUDA, but this host has the NVIDIA driver and
CUDA runtime without `nvcc`, so that feature could not be built. Its CPU result
is intentionally reported rather than silently substituting WSL. The official
vLLM path was also not replaced by WSL or a community fork: vLLM documents
Linux as the supported OS and says Windows is not supported natively. A clean
Python 3.12 environment confirmed the boundary: `uv pip install --dry-run "vllm[audio]>=0.15.0"`
could not resolve a Windows distribution.

## Reproduce

Build the corpus once:

```powershell
py -3.12 evals\stt_accent_corpus.py "$env:LOCALAPPDATA\Marvi-OS\evals\stt-candidates\corpus"
```

Each runtime runner writes one JSONL row per manifest clip. Score any completed
run with the shared scorer:

```powershell
py -3.12 evals\stt_score.py <manifest.jsonl> <predictions.jsonl> --output <score.json>
```

The runners deliberately stay evaluation-only. A candidate still needs the
real LiveKit adapter, physical speaker loop, barge-in, device recovery, and
60-minute soak before it can become selectable or default.
