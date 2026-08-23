# Upstream Reuse Ledger

Nothing in this table is vendored merely because it is listed. Pinning and
integration happen only when its delivery phase begins. Every adopted entry must
be updated with the exact version/commit and local modification path.

| Capability | Upstream | License/terms | Strategy | Status |
|---|---|---|---|---|
| Agent framework | [livekit/agents](https://github.com/livekit/agents) | Apache-2.0 | dependency; never fork session plumbing | selected |
| Agent scaffold | [livekit-examples/agent-starter-python](https://github.com/livekit-examples/agent-starter-python) | MIT | scaffold with provenance, then keep dependencies upstream | selected |
| Local RTC server | [livekit/livekit](https://github.com/livekit/livekit) 1.13.5 | Apache-2.0 | checksummed Windows binary managed locally | adopted |
| Desktop RTC client | [livekit/client-sdk-js](https://github.com/livekit/client-sdk-js) | Apache-2.0 | package dependency | selected |
| Desktop scaffold | [electron-vite/electron-vite](https://github.com/alex8088/electron-vite) via `@quick-start/electron` | MIT | generated React/TypeScript process skeleton; replace demo UI | adopted |
| React media primitives | [livekit/components-js](https://github.com/livekit/components-js) | Apache-2.0 | reuse only needed hooks/primitives; Island remains custom | selected |
| Wake lifecycle reference | [livekit-examples/hello-wakeword](https://github.com/livekit-examples/hello-wakeword) | verify at pin | adapt lifecycle, not bespoke RTC | selected reference |
| Kyutai streaming TTS | [kyutai-labs/delayed-streams-modeling](https://github.com/kyutai-labs/delayed-streams-modeling) | Python MIT; Rust Apache-2.0; verify TTS checkpoint terms | native-Windows streaming hardware spike | evaluating |
| Unmute architecture | [kyutai-labs/unmute](https://github.com/kyutai-labs/unmute) | verify at pin | architecture/reference only; full runtime rejected for 12 GB/native Windows | reference |
| STT primary candidate | [moonshine-ai/moonshine](https://github.com/moonshine-ai/moonshine) | MIT code and English models; review non-English model terms | native Windows C++/ONNX streaming adapter | evaluating |
| STT packaging fallback | [k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | Apache-2.0 code; verify selected model | native Windows streaming runtime | evaluating |
| STT runtime | [altunenes/parakeet-rs](https://github.com/altunenes/parakeet-rs) 0.3.7 | MIT OR Apache-2.0 | thin native CUDA sidecar; no ASR reimplementation | adopted |
| STT model | [NVIDIA Nemotron 3.5 ASR Streaming 0.6B](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b) via ONNX export `a61d2818` | OpenMDW-1.1 model terms | stateful 16 kHz streaming with explicit locale | adopted |
| TTS runtime/model | [microsoft/VibeVoice](https://github.com/microsoft/VibeVoice) `94da20d` / model `6bce5f0` | MIT repository; model card terms | official 0.5B acoustic streaming model + thin adapter | adopted |
| TTS research challenger | [canopyai/Orpheus-TTS](https://github.com/canopyai/Orpheus-TTS) | Apache-2.0 | benchmark only if primary paths fail | parked |
| Local end-of-turn | [livekit/agents](https://github.com/livekit/agents) `TurnDetector v1-mini` | LiveKit model license | pin local CPU model explicitly; never cloud auto-select | selected |
| Tool protocol | [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) `mcp` 1.x | MIT | Gateway-side client so MCP tools inherit confirmation and audit (ADR-016); not attached to the Agent | adopted |
| Account tools | [ComposioHQ/composio](https://github.com/ComposioHQ/composio) `composio` 0.19.0 / `composio-client` 1.43.0 | MIT SDK; hosted-service terms separate | official SDK behind a thin adapter; Composio owns OAuth and Marvi OS never holds provider credentials | adopted |
| Memory candidate | [mem0ai/mem0](https://github.com/mem0ai/mem0) 2.0.18 | Apache-2.0 | rejected for now: hard dependency on `openai`, `qdrant-client`, and `posthog` telemetry (ADR-014) | rejected |
| Persistent mind candidate | [letta-ai/letta](https://github.com/letta-ai/letta) 0.16.8 | Apache-2.0 | rejected after measurement against the mind gates: unmaintained Docker path, Postgres+pgvector, owns the prompt and the background budget, and is a foreground LLM rather than a decision layer (ADR-018) | rejected |
| Voice-memory reference | [letta-ai/letta-voice](https://github.com/letta-ai/letta-voice) | MIT | reference only; example cloud voice providers conflict with local contract | reference |
| Reflection reference | [letta-ai/letta-code](https://github.com/letta-ai/letta-code) | Apache-2.0 | study memory/reflection patterns; do not embed its CLI | reference |
| Proactive scheduler | [agronholm/apscheduler](https://github.com/agronholm/apscheduler) 3.11.3 | MIT | four bounded background ticks owned by the Gateway; jobs guarded so one failure cannot kill the schedule | adopted |
| Durable agent graph | [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | MIT | revisit only after a measured workflow outgrows Gateway jobs + LiveKit tasks | deferred |
| Durable execution | [temporalio/sdk-python](https://github.com/temporalio/sdk-python) | MIT | operationally excessive for initial single-PC product | deferred |
| Proactive TTS | [kyutai-labs/pocket-tts](https://github.com/kyutai-labs/pocket-tts) 2.1.0 | see model card | 100M-parameter CPU TTS for one-shot announcements; published into the LiveKit room so the client's AEC applies (ADR-019) | adopted |
| Face recognition | [deepinsight/insightface](https://github.com/deepinsight/insightface) 0.7.x, `buffalo_l` | MIT code; model card terms | CPU-only ONNX embeddings behind a motion gate so vision never competes with the voice stack for VRAM | adopted |
| Camera capture | [opencv/opencv-python](https://github.com/opencv/opencv-python) headless 4.x | Apache-2.0 | capture and JPEG crops only; no display stack pulled in | adopted |
| Browser automation | [microsoft/playwright-python](https://github.com/microsoft/playwright-python) 1.62.0 | Apache-2.0 | one long-lived Chromium page behind the Gateway; reuses the already-cached browser, no anti-detect stack | adopted |
| Web search | [Brave Search API](https://brave.com/search/api/) / SearXNG | commercial API terms / AGPL-3.0 self-hosted | env-selected provider behind one adapter; results always enveloped | adopted |
| Memory store | Python stdlib `sqlite3` + FTS5 (SQLite 3.50.4) | PSF / public domain | local episodic and semantic memory behind a provider seam; no vector database or embedding model | adopted |
| Smart Room | `D:\smart-room-plugin` (running copy `the room sidecar` 0.6.0) | internal | independent sidecar; Marvi OS is a client of its authenticated loopback JSON-RPC and never holds device credentials | adopted |
| Dynamic Island source | `the predecessor desktop's voice island` | internal | extract focused visual/state pieces with provenance; no voice transport | selected |
| Desktop brand font | `@nous-research/ui` 0.18.2 `Collapse-Bold.woff2` via `the predecessor assistant` | MIT package | copied font asset; update from the pinned package when Marvi typography changes | adopted |
| Desktop mono font | JetBrains Mono faces via `the predecessor desktop's font assets` | Apache-2.0 | copied Regular/Bold/Italic WOFF2 assets; preserve metrics and license | adopted |
| Update mechanism source | the predecessor desktop updater (`electron/updater-process.ts`, `scripts/desktop-update/windows.ps1`) | internal | adapted the handoff contract — pid wait, marker, result file, rollback — rewritten as the Tauri bootstrap (see below); the PowerShell script is replaced | adopted |
| Tauri | [tauri](https://github.com/tauri-apps/tauri) 2.x | MIT/Apache-2.0 | thin GUI shell around `marvi-bootstrap-core`; minimal static window, no frontend bundler; binary named `marvi-bootstrap.exe` (a neutral name so Windows installer detection never auto-elevates it) | dependency |
| Dynamic Island orb | [Jakubantalik/thinking-orbs](https://github.com/Jakubantalik/thinking-orbs) 0.3.1 | MIT | vendored geometry engine (`src/renderer/src/orb/engine/`, `presets.ts`) unchanged except dropping an unused `rMin` param; Marvi's own painter colors the dots per phase and the component is rewritten | adopted |
| Frameless title bar pattern | `the predecessor assistant\apps\desktop\electron\main.ts` (`titleBarStyle:'hidden'`, overlay options) | internal | adapt hidden-titlebar shell to renderer-painted chrome | adopted |
| Glyph spinner | [unicode-animations](https://www.npmjs.com/package/unicode-animations) 1.0.3 | MIT | dependency; braille/orbit frames for CONNECTING and busy states | adopted |
| Web haptics | [web-haptics](https://github.com/lochie/web-haptics) 0.0.6 | MIT | dependency; audio-transducer tap/selection/success/error feedback | adopted |
| Composer border motion | [Jakubantalik/border-beam](https://github.com/Jakubantalik/border-beam) 1.3.0 | MIT | unmodified dependency; monochrome line preset wraps the existing Chat composer, with Marvi retaining all controls and behavior | adopted |
| Context menu primitive | [radix-ui](https://github.com/radix-ui/primitives) 1.6.7 | MIT | dependency; ContextMenu only (shell context menu) | adopted |
| Shell chrome adaptation | `the predecessor assistant\apps\desktop\src\components\` (decode-text, glyph-spinner, gateway-connecting-overlay, boot-failure-overlay, haptics-provider, translucency, background store, shell-context-menu) | internal | adapt with provenance; local-only, no remote fetches | adopted |
| Electric Gaze backdrop | 21st.dev ascii-recipe render `assets.21st.dev/ascii-recipes/.../c458eb38-....mp4` (412 KB) + poster webp | verify at re-fetch | vendored local asset; never fetched at runtime | adopted |

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
- A permanent autonomous LLM loop: activity is not agency; cognition is
  event-driven and bounded by relevance, quiet hours, and cost policy.
