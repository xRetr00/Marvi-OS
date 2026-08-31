# Streaming TTS challengers — 31 August 2026

Six newly released TTS paths were checked against Marvi's native-Windows,
full-duplex voice gates. This is a candidate screen and short synthesis trial,
not a selection bakeoff: listening, a real LiveKit loopback session, combined
STT/TTS residency, interruption, and the 60-minute soak are still required.

## Decision

**Keep Kokoro as the shipping voice.** CuteTTS-distill is the only candidate
worth advancing to a listening and adapter spike. VoXtream2 is the second
choice because it accepts incremental text as well as emitting incremental
audio, but its Windows runtime is rougher and slower. The other four are
rejected or parked before integration.

| Candidate | Native Windows | Streaming evidence | RTX 3060 result | Decision |
| --- | --- | --- | --- | --- |
| CuteTTS-distill ~0.23B | runs only after selecting the upstream eager sampler | 160 ms PCM chunks while autoregressive generation continues | 85 ms warm first audio; 0.31 RTF; 1.53 GiB peak allocated | **advance, not adopt** |
| VoXtream2 ~0.5B | runs only with TorchDynamo eager fallback; shutdown error remains | full-stream incremental text plus 80 ms PCM chunks | 394 ms warm first audio; 0.47 full-text / 0.65 incremental-text RTF; 1.70 GiB peak | **park behind CuteTTS** |
| VoxCPM2 2B | official PyTorch path runs | 160 ms output chunks, but input is a complete string | 342 ms warm first audio; 2.09 RTF; 5.47 GiB peak; only 1.44 GiB system VRAM remained | **reject** |
| Breeze-TTS-2.cpp 3B | source config needs a separately installed Vulkan SDK | HTTP/WebSocket path; vocoder decodes two-second chunks | not run; upstream reports about 1.2x realtime at Q8 on RTX 3060 | **reject: non-commercial weights** |
| Gepard 1.0 ~0.56B | official setup and optimized vLLM serving path are Linux-oriented | streaming-first 22.05 kHz codec LM | not run on Windows | **park: no supported Windows serving path** |
| CTC-TTS-F 0.03B/0.16B | released environment pins FlashAttention, CUDA 11.8-era Torch, NeMo, and shell orchestration | paper/repository demonstrate dual streaming | not run | **reject pending an explicit weight/code license and Windows package** |

The warm first-audio figures exclude model loading but include prompt/text
preparation. RTF is wall-clock synthesis time divided by emitted audio length;
lower is better and values above 1.0 are slower than playback.

## Machine and pins

- Windows, NVIDIA GeForce RTX 3060 12 GB, driver 610.88.
- Python 3.12.0, PyTorch 2.5.1+cu121 for the Python trials.
- CUDA process measurements used `torch.cuda.max_memory_allocated`; system free
  memory was also recorded because codec and driver allocations do not all
  appear in the PyTorch allocator.
- Three fixed English texts: an ordinary Marvi reply, a proper-noun/number
  stress line, and a longer continuity line. The same seed was used where the
  upstream API exposed one.
- Generated audio was passed back through Marvi's installed English-only
  Parakeet v2 recognizer on CPU. That WER is an intelligibility smoke test, not
  a naturalness score.

| Project | Source commit | Model revision |
| --- | --- | --- |
| [CTC-TTS](https://github.com/THU-SPMI/CTC-TTS) | `7b308b7762564a53e398482a5ec0685d4d9c7e9f` | [`1e568e2a03d9664037344fbccf23163a5b9b0cf7`](https://huggingface.co/THU-SPMI/CTC-TTS/tree/1e568e2a03d9664037344fbccf23163a5b9b0cf7) |
| [Breeze-TTS-2.cpp](https://github.com/HoppouAI/Breeze-TTS-2.cpp) | `610d705c28f5490d1228eedde3e5b426f529e909` | [`81b22bad9f05b99970e30c5ee5e4bbc52fedf2f8`](https://huggingface.co/HoppouAI/Breeze-TTS-2.cpp/tree/81b22bad9f05b99970e30c5ee5e4bbc52fedf2f8) |
| [VoxCPM](https://github.com/OpenBMB/VoxCPM) | `f5a1c6a6b901bc732e20f0d59a369f6829ad717a` | [`32279effe8c19989596f05d353d1447f51d9e915`](https://huggingface.co/openbmb/VoxCPM2/tree/32279effe8c19989596f05d353d1447f51d9e915) |
| [Gepard inference](https://github.com/nineninesix-ai/gepard-inference) | `eb87bc49ed75a806613168ed7eddb44b5ef1f737` | [`56a5f18e76b6dab83039090083a3acec161f7777`](https://huggingface.co/nineninesix/gepard-1.0/tree/56a5f18e76b6dab83039090083a3acec161f7777) |
| [CuteTTS](https://github.com/OPPO-Mente-Lab/CuteTTS) | `ca9dbd3b82c05f5b067466088449b93ee2aa5a0c` | [`6f84092f441295c415019193424033c93c6aee68`](https://huggingface.co/OPPOer/CuteTTS-distill/tree/6f84092f441295c415019193424033c93c6aee68) |
| [VoXtream2](https://github.com/herimor/voxtream) | `8ec2d62159dae4716ae7058827244a962d40603c` | [`49addec130217e8e9e82a6f49437c315c5c851fc`](https://huggingface.co/herimor/voxtream2/tree/49addec130217e8e9e82a6f49437c315c5c851fc) |

## Measured candidates

### CuteTTS-distill

The model loaded in 27.80 seconds and held 1.17 GiB allocated after load. After
one explicit warm-up, the three trials were:

| Text | First audio | RTF | Audio | Chunks | Parakeet WER |
| --- | ---: | ---: | ---: | ---: | ---: |
| ordinary | 120 ms | 0.318 | 4.00 s | 25 | 0/13 |
| names and number | 85 ms | 0.312 | 5.60 s | 35 | 5/15 |
| long continuity | 62 ms | 0.298 | 10.40 s | 65 | 0/30 |

The five errors were proper nouns: variants of Shereef, Marvi, NeuDocs, and
Düzce. That is exactly the class Marvi's vocabulary correction already
handles, although the audio still needs a human pronunciation judgment.

The upstream CUDA default does not run on stock native Windows: it selects a
TorchInductor/Triton sampler and fails because Triton is absent. Selecting the
library's own eager sampler produced the measurements above. Adding
`triton-windows==3.1.0.post17` did not repair the pinned Torch 2.5.1 path; the
compile failed in TorchInductor's atomic cache rename with `WinError 183` even
with a fresh isolated cache. A Marvi adapter would therefore need an explicit
eager selection or an upstream-tested newer Torch pin.

### VoXtream2

The cached stack loaded in 5.46 seconds. It includes the main model, two Mimi
codec instances, ReDimNet speaker encoder, Silero VAD, eSpeak, and runtime NLTK
data. That is a substantially broader installation boundary than the model
repository size suggests.

| Text/input | First audio | RTF | Audio | Chunks | Parakeet WER |
| --- | ---: | ---: | ---: | ---: | ---: |
| ordinary/full text, first request | 3,711 ms | 1.303 | 4.80 s | 60 | 1/13 |
| names/full text, warm | 391 ms | 0.473 | 6.56 s | 82 | 7/15 |
| long/incremental text, warm | 397 ms | 0.651 | 13.28 s | 166 | 1/30 |

Each audio frame is 80 ms; median frame computation was 33 ms. The first
request paid failed compilation/fallback initialization. This is the strongest
full-stream architecture in the group because text can arrive word by word,
but the upstream Moshi dependency still attempts Triton compilation on Windows.
Allowing TorchDynamo to fall back to eager made it run, emitted a large warning,
and ended with a `multiprocess.resource_tracker` cleanup error.

### VoxCPM2

The official model is 2B parameters and 4.62 GB on disk. It loaded in 32.91
seconds, allocated 5.06 GiB resident, and peaked at 5.47 GiB allocated.

| Text | First audio | RTF | Audio | Parakeet WER |
| --- | ---: | ---: | ---: | ---: |
| ordinary, first request | 8,914 ms | 3.847 | 4.96 s | 0/13 |
| names and number, warm | 342 ms | 2.087 | 6.08 s | 5/15 |

Warm first audio passes the latency gate, but continuing generation is slower
than playback and system free VRAM fell from 10.99 GiB to 1.44 GiB. It cannot
share the 12 GB card safely with the rest of Marvi and is rejected.

## Screened without a full synthesis run

### Breeze-TTS-2.cpp

The Apache-2.0 C++ runtime is not enough: the model weights use the
BreezeBlue Research and Non-Commercial License, so they cannot be Marvi's
shipping voice. A real native build was also attempted and CMake stopped
because the Vulkan library, headers, and `glslc` were not installed. The model
is 3B parameters; Q8 is 3.32 GB and upstream estimates roughly another 1 GB of
VRAM. Its two-second vocoder chunks are also coarse for interruption compared
with the 80–160 ms challengers.

### Gepard 1.0

The model and inference code are Apache-2.0, while NVIDIA NanoCodec has its own
open-model terms. Gepard is attractive on paper: a single-pass streaming codec
LM and very low reported latency on RTX 5090/server hardware. The reference
repository's setup uses Bash, `apt`, Linux venv paths, NeMo, and an imperative
dependency repair sequence; the optimized serving path is vLLM. That is not a
supported native-Windows package and the reported server numbers are not
portable to this RTX 3060. Do not introduce inference into Electron's renderer
through a browser/WebGPU wrapper to bypass the service boundary.

### CTC-TTS-F

CTC-TTS-F is small and genuinely interesting: the released single-speaker and
multi-speaker variants are 33.6M and 158.5M parameters. The authors report 159
ms first-packet latency for the single-speaker model and 5.20% WER for the
multi-speaker continuation task. However, the repository and Hugging Face card
do not declare a license. The environment also pins Torch 2.6.0+cu118,
FlashAttention 2.7.3, NeMo 1.21.0, older Transformers/tokenizers, and shell
entry points. It cannot enter a shipping bakeoff until licensing and a
maintained native-Windows inference package are explicit.

## What remains before any switch

1. Blind listening against Kokoro using the owner's preferred voice and the
   real Marvi failure corpus: names, Turkish words, numbers, abbreviations,
   questions, short acknowledgements, and long replies.
2. A thin LiveKit TTS adapter test proving cancellation stops generation and
   queued playout without creating a second scheduler.
3. Combined CPU Parakeet plus candidate TTS residency, real speaker loopback,
   echo/self-transcription, barge-in, device switch, sleep/resume, crash
   recovery, and a 60-minute soak.
4. A pinned, one-command native-Windows installation with no first-run network
   downloads and complete checksums in `config/voice-models.json`.
5. Only after those pass: update `docs/UPSTREAM.md`, the runtime contract,
   Setup, tests, README, phase evidence, and the selected model manifest in one
   milestone.
