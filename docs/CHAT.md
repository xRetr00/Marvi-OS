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
- Durable ordered parts distinguish text, attachments, sources, reasoning, and
  tools. The visible assistant prose is never reconstructed from reasoning.
- The composer accepts drag/drop and file selection. Images are capability
  checked and translated to each provider's official message shape. Supported
  documents are extracted locally with MarkItDown, size capped, and wrapped as
  untrusted external content before provider use.
- Dictation sends 16 kHz mono PCM through Electron to a bounded Gateway
  session backed by the already-installed native Nemotron STT sidecar. The
  renderer does not run inference or persist microphone audio.
- Assistant output renders sanitized GitHub-flavored Markdown, tables, task
  lists, syntax-preserving code blocks, and KaTeX math. Raw HTML is disabled.
- Read aloud uses installed Windows/browser speech voices. Only settled,
  visible assistant prose is spoken; Markdown structure is made natural while
  code, URLs, reasoning, tools, and external source bodies are omitted.
- Source links extracted from settled assistant Markdown appear as bounded
  source cards. This is provenance display, not a claim that every provider
  supports native citations.

Dynamic follow-up suggestions are deliberately not part of the product
contract. The renderer does not invent suggestion chips and the Gateway does
not generate or persist them.

## UI composition

The page adapts Assistant UI's interaction structure into Marvi's monochrome
control-center language without adopting a second runtime: a bounded reading
column, compact user surfaces, unboxed Marvi replies, visible source/evidence
modules, sticky composer, thread drawer, message actions, and explicit
return-to-latest control. Empty-state prompts only fill the composer and never
pretend to be model output.

The composer keeps Marvi's provider/model/effort controls, attachment queue,
context breakdown, microphone action, stop/send state, and the state-driven
monochrome border beam. Every ambiguous action has a tooltip and accessible
name.

## Boundaries and acceptance

- Two threads must survive restart without mixing history or model selection.
- Editing and regenerating must preserve the prior branch.
- Attachment files are local, removed with their owning thread, and never sent
  through an unsupported image route.
- Dictation must exercise the native sidecar protocol rather than a renderer
  mock.
- Read aloud must never speak streaming partials, code, URLs, reasoning, tool
  payloads, or document contents.
- Markdown output must remain readable with scripts disabled and cannot execute
  model-authored HTML.

The frontend pattern reference remains pinned to Assistant UI commit
`105af3eaea2093df271d9c44642e1c04d5f5cf7c`. Upstream Markdown, speech-policy,
and document extraction provenance is recorded in `docs/UPSTREAM.md`.
