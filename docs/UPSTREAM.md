# Upstream Reuse Ledger

Nothing in this table is vendored merely because it is listed. Pinning and
integration happen only when its delivery phase begins. Every adopted entry must
be updated with the exact version/commit and local modification path.

| Capability | Upstream | License/terms | Strategy | Status |
|---|---|---|---|---|
| Agent framework | [livekit/agents](https://github.com/livekit/agents) | Apache-2.0 | dependency; never fork session plumbing | selected |
| Agent scaffold | [livekit-examples/agent-starter-python](https://github.com/livekit-examples/agent-starter-python) | MIT | scaffold with provenance, then keep dependencies upstream | selected |
| Local RTC server | [livekit/livekit](https://github.com/livekit/livekit) | Apache-2.0 | pinned Windows binary managed by Gateway | selected |
| Desktop RTC client | [livekit/client-sdk-js](https://github.com/livekit/client-sdk-js) | Apache-2.0 | package dependency | selected |
| Desktop scaffold | [electron-vite/electron-vite](https://github.com/alex8088/electron-vite) via `@quick-start/electron` | MIT | generated React/TypeScript process skeleton; replace demo UI | adopted |
| React media primitives | [livekit/components-js](https://github.com/livekit/components-js) | Apache-2.0 | reuse only needed hooks/primitives; Island remains custom | selected |
| Wake lifecycle reference | [livekit-examples/hello-wakeword](https://github.com/livekit-examples/hello-wakeword) | verify at pin | adapt lifecycle, not bespoke RTC | selected reference |
| Kyutai streaming TTS | [kyutai-labs/delayed-streams-modeling](https://github.com/kyutai-labs/delayed-streams-modeling) | Python MIT; Rust Apache-2.0; verify TTS checkpoint terms | native-Windows streaming hardware spike | evaluating |
| Unmute architecture | [kyutai-labs/unmute](https://github.com/kyutai-labs/unmute) | verify at pin | architecture/reference only; full runtime rejected for 12 GB/native Windows | reference |
| STT primary candidate | [moonshine-ai/moonshine](https://github.com/moonshine-ai/moonshine) | MIT code and English models; review non-English model terms | native Windows C++/ONNX streaming adapter | evaluating |
| STT packaging fallback | [k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | Apache-2.0 code; verify selected model | native Windows streaming runtime | evaluating |
| STT quality challenger | [NVIDIA-NeMo/NeMo](https://github.com/NVIDIA-NeMo/NeMo) | Apache-2.0 code; verify Nemotron model terms | native-Windows feasibility spike only | evaluating |
| TTS fallback | [microsoft/VibeVoice](https://github.com/microsoft/VibeVoice) | MIT repository; verify model card and release terms | official 0.5B realtime model + thin adapter | evaluating |
| TTS research challenger | [canopyai/Orpheus-TTS](https://github.com/canopyai/Orpheus-TTS) | Apache-2.0 | benchmark only if primary paths fail | parked |
| Local end-of-turn | [livekit/agents](https://github.com/livekit/agents) `TurnDetector v1-mini` | LiveKit model license | pin local CPU model explicitly; never cloud auto-select | selected |
| Tool protocol | [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) | MIT | pinned dependency; version chosen after LiveKit compatibility check | selected |
| Account tools | [ComposioHQ/composio](https://github.com/ComposioHQ/composio) | MIT SDK; hosted-service terms separate | official SDK, no bespoke provider OAuth where supported | selected |
| Memory candidate | [mem0ai/mem0](https://github.com/mem0ai/mem0) | Apache-2.0 | benchmark against extracted Marvi memory needs | evaluating |
| Smart Room | `D:\smart-room-plugin` | internal | independent sidecar; reuse bridge/event bus first | selected |
| Dynamic Island source | `D:\hermes-agent\apps\desktop\src\app\voice-island` | internal | extract focused visual/state pieces with provenance; no voice transport | selected |
| Desktop brand font | `@nous-research/ui` 0.18.2 `Collapse-Bold.woff2` via `D:\hermes-agent` | MIT package | copied font asset; update from the pinned package when Marvi typography changes | adopted |
| Desktop mono font | JetBrains Mono faces via `D:\hermes-agent\apps\desktop\src\fonts` | Apache-2.0 | copied Regular/Bold/Italic WOFF2 assets; preserve metrics and license | adopted |
| Update mechanism source | `D:\hermes-agent\apps\desktop\electron\updater-process.ts` and `D:\hermes-agent\scripts\desktop-update` | internal | extract/adapt tested repo-owned Windows handoff | selected |

## Update procedure

For each upstream dependency:

1. Review changelog, security advisories, and license changes.
2. Update the pinned version/commit in this ledger.
3. Run its boundary tests and Marvi OS integration tests.
4. Re-run latency/VRAM benchmarks for voice or media dependencies.
5. Record local patches; upstream generally useful fixes whenever practical.

Do not silently vendor snapshots. Do not point production builds at moving
branches.

## Explicitly rejected voice paths

- Whisper-family runtimes: overlapping-window transcription is not the required
  stateful incremental STT architecture.
- Qwen3-TTS: too heavy for the shared always-on RTX 3060 budget.
- Full Unmute deployment: Linux/WSL and VRAM requirements conflict with the
  native-Windows product contract.
- Sentence-buffered TTS wrappers: they cannot meet the duplex interruption and
  continuous-playout contract.
