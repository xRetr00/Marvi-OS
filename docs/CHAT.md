# Chat Surface

Chat is a typed transport through the same Marvi Gateway used by Voice. The
Gateway is authoritative for threads, branches, messages, tools,
confirmations, provider routing, attachments, and usage. Electron exposes only
the bounded operations the renderer needs; React owns presentation and
ephemeral input state.

## Implemented contract

- SQLite-backed threads survive restart and support create, select, rename,
  archive, and delete. Provider, model, and effort selection is stored per
  thread so conversations cannot silently share overrides.
- Messages have parent and branch identity. Editing an earlier user turn or
  regenerating an answer selects a new branch without deleting the original.
- Durable ordered parts distinguish text, attachments, sources, reasoning,
  tools, and a finite validated widget vocabulary. The visible assistant prose
  is never reconstructed from reasoning.
- The composer accepts drag/drop and file selection. Images are capability
  checked and translated to each provider's official message shape. Supported
  documents are extracted locally with MarkItDown, size capped, and wrapped as
  untrusted external content before provider use.
- Dictation sends 16 kHz mono PCM through Electron to a bounded Gateway
  session backed by an Agent-owned Parakeet TDT ONNX worker. The renderer does
  not run inference or persist microphone audio.
- Assistant output renders sanitized GitHub-flavored Markdown, tables, task
  lists, syntax-preserving code blocks, and KaTeX math. Raw HTML is disabled.
- Read aloud calls the active local LiveKit agent and therefore uses Marvi's
  configured Kokoro voice and normal LiveKit playout/interruption path. Chat
  opens an audio-only room when Voice is not already connected. Only settled,
  visible assistant prose is spoken; Markdown structure is made natural while
  code, URLs, reasoning, tools, and external source bodies are omitted.
- Web-search evidence becomes a structured source widget at the tool boundary,
  so links do not disappear when a model omits them from final prose. Markdown
  links remain a fallback; neither path claims unsupported native citations.
- The context ring uses the provider-reported input-token count and the pinned
  model catalog's context window. Unknown values display as unknown rather than
  estimates; the breakdown also exposes cache, reply reserve, message, file,
  source, and route facts.

Dynamic follow-up suggestions are deliberately not part of the product
contract. The renderer does not invent suggestion chips and the Gateway does
not generate or persist them.

## UI composition

The page adapts Assistant UI's interaction structure into Marvi's monochrome
control-center language without adopting a second runtime: a bounded reading
column, compact user surfaces, unboxed Marvi replies, visible source/evidence
modules, sticky composer, message actions, and explicit return-to-latest
control. While Chat is active, the app navigation is replaced by the searchable
conversation sidebar adapted from the pinned upstream desktop; it exposes recent
threads and their actions without a drawer or redundant page header. Empty-state
prompts only fill the composer and never pretend to be model output.

The composer keeps Marvi's provider/model/effort controls, attachment queue,
context breakdown, microphone action, and stop/send state inside a rounded,
quiet paper surface sized to the compact 560px transcript. Human prompts use
one slim full-row surface and Marvi replies remain unboxed prose directly below
them; sender names stay accessible without becoming repeated visual headers.
Timestamps and message actions live in the quiet hover/focus rail. Every
ambiguous action has a tooltip and accessible name.

Generative output follows Assistant UI's tool-UI pattern through a Marvi-owned
adapter. Models may request only `sources`, `metrics`, `comparison`, `table`,
`timeline`, `weather`, `gallery`, `document`, or `status`; the Gateway validates,
caps, persists, and streams plain data. React selects the component from that
allowlist. Model-authored code, component names, callbacks, and actions are not
accepted. Rendering follows the pinned upstream rather than a custom card skin:
transparent tool disclosures, a small `Sources · count` row, flat source links,
thin divided structured results, and no repeated widget-type banner.

## Boundaries and acceptance

- Two threads must survive restart without mixing history or model selection.
- Editing and regenerating must preserve the prior branch.
- Attachment files are local, removed with their owning thread, and never sent
  through an unsupported image route.
- Dictation must exercise the bounded Parakeet worker protocol rather than a
  renderer mock.
- Read aloud must never speak streaming partials, code, URLs, reasoning, tool
  payloads, or document contents, and must not create a duplicate Voice chat
  item.
- Markdown output must remain readable with scripts disabled and cannot execute
  model-authored HTML.
- Widgets must replay from stored parts exactly as they appeared live, and
  invalid/private-URL data must be rejected at the Gateway boundary.

The frontend pattern reference remains pinned to Assistant UI commit
`105af3eaea2093df271d9c44642e1c04d5f5cf7c`. Upstream Markdown, speech-policy,
and document extraction provenance is recorded in `docs/UPSTREAM.md`.
