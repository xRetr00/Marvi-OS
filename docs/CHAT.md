# Chat Surface

Chat is a typed transport for the same Marvi session used by Voice. The
Gateway remains authoritative for messages, tools, confirmations, provider
routing, and durable usage. The renderer owns layout and ephemeral interaction.

## Current frontend contract

The Chat page adapts the interaction structure of Assistant UI into Marvi's
monochrome control-center language:

- a bounded reading column inside a full-height thread viewport;
- a sticky, auto-growing composer with model and reasoning-effort overrides;
- user bubbles, unboxed assistant replies, and compact message action bars;
- collapsed reasoning and tool evidence;
- pinned scrolling with an explicit return-to-latest control;
- local starter prompts that fill the composer without pretending to be model
  output;
- transcript export generated locally from the already-loaded messages;
- streaming, cancellation, confirmations, timing, and usage wired through the
  existing Gateway and Electron bridge.

The first frontend adaptation is pinned to Assistant UI commit
`105af3eaea2093df271d9c44642e1c04d5f5cf7c`. No Assistant UI runtime was added:
Marvi already has an authoritative streaming runtime, and adding a second state
engine would make the transcript race itself.

## Backend-dependent Assistant UI capabilities

These controls must not appear until their contracts exist. A disabled or fake
button is not an implementation.

| Capability | Required backend work | Acceptance boundary |
|---|---|---|
| Multiple threads | Add `threads`; scope messages to a thread; expose list, create, select, rename, archive, and delete; mirror through narrow Electron IPC. | Two threads survive restart and never mix history, model overrides, or confirmations. |
| Edit, regenerate, and branches | Add message ancestry and branch identity; implement transactional edit/regenerate and active-branch selection. | Editing an old user turn creates a branch without destroying the original and usage is recorded only for generated work. |
| Attachments and dropzone | Define type/size policy, local storage lifecycle, multipart ingestion, typed attachment rows, and provider capability routing. | Image and document attachments survive the turn, are removable before send, and never leak outside the selected provider path. |
| Dynamic follow-ups | Emit structured suggestion records after a completed turn and persist only when product policy requires it. | Suggestions correspond to the active branch and disappear when stale; no renderer-generated model claims. |
| Sources, files, and images | Replace the plain message body boundary with ordered typed content parts in streaming events and durable history. | Text, source, file, image, reasoning, and tool parts round-trip in order without flattening untrusted content into prose. |
| Composer dictation | Expose the existing local streaming STT session through bounded Gateway/Electron transcription events. | Chat dictation shares the installed STT engine and microphone authority; it does not create a browser or renderer inference path. |

## Recommended backend sequence

1. Introduce thread identity and migrations while preserving the current
   transcript as the default thread.
2. Introduce typed content parts and attachment policy before exposing any
   file control.
3. Add branch-safe edit/regenerate operations on the typed thread model.
4. Add structured sources and dynamic suggestions to the stream protocol.
5. Add the renderer-facing dictation adapter over the existing voice/STT
   boundary.
6. Add each frontend control only after its contract and boundary tests pass.
