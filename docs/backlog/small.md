# Backlog — small

A day or less each. Most are follow-ups to the ten shipped on 2026-09-16.

## S1. Paste an image into the chat box

**Why.** The composer accepts drag/drop and a file picker; Ctrl+V of a
screenshot does nothing. Hermes has image paste.

**Plan.** `onPaste` in the composer turns `clipboardData.files` images into the
same attachment upload the picker uses. Renderer only.

**Done when.** Win+Shift+S then Ctrl+V attaches the screenshot.

## S2. `@file` and `@url` in the chat box

**Why.** Hermes injects files, folders, diffs and URLs with `@`. Marvi needs a
drag or a tool call.

**Plan.** `@` opens a picker (workspace files via `file_search`, or a pasted
URL); the chosen item becomes an attachment (file) or a `web_extract` result
wrapped as untrusted (URL).

**Done when.** `@notes.md summarise this` answers from the file without a tool
call.

## S3. Clipboard images (*extends #2*)

**Plan.** `clipboard_read` also reads `CF_DIB`; an image is sent to the
`vision` role like `read_screen` and comes back as words.

**Done when.** "What's in the image I copied?" is answered.

## S4. What is playing, and exact volume (*extends #3*)

**Why.** `media_control` presses keys; it cannot say what is playing or set
"volume to 30".

**Upstream.** Windows `GlobalSystemMediaTransportControlsSessionManager` (via
the `winrt-*` packages) for now-playing; Core Audio `IAudioEndpointVolume` (via
`pycaw`, MIT) for the level.

**Plan.** `media_now` tool (title, artist, app) and an optional `level` argument
on `media_control`; record both packages in `UPSTREAM.md`.

**Done when.** "What song is this?" and "volume 30" work with Spotify.

## S5. Summon hotkey in Settings (*extends #10*)

**Plan.** A field in Settings → Voice that records a key combination, writes
`MARVI_SUMMON_HOTKEY`, and re-registers without a restart; shows "taken by
another app" when registration fails.

**Done when.** Changing the hotkey takes effect immediately.

## S6. Push-to-talk hold

**Plan.** Holding the summon hotkey keeps the microphone open until release
(Electron `globalShortcut` has no key-up, so this uses the pet-host's native
keyboard hook or `uiohook-napi`, MIT; record it).

**Done when.** Hold-to-talk works in a noisy room with the wake word off.

## S7. File changes on the Activity page (*extends #1*)

**Plan.** Checkpoints appear in Activity as "Marvi changed notes.md" with a
Restore button that goes through `file_restore` (and so through confirmation).

**Done when.** A change made by Harvi can be undone from the Activity page.

## S8. Scheduled Obsidian export (*extends #9*)

**Plan.** A cron action that runs the vault export nightly to a chosen folder;
no new code beyond wiring `vault.export` as a job action.

**Done when.** The vault is current every morning without a command.

## S9. Export a chat thread

**Plan.** Thread menu → Export as Markdown (messages, sources, attachments
listed); uses the same store rows as `/chat`.

**Done when.** An exported thread opens cleanly in any Markdown viewer.

## S10. Read Windows notifications

**Why.** Seeing a WhatsApp Desktop or Teams toast would give Marvi messages
without the WhatsApp ban risk noted in the messaging research.

**Upstream.** `UserNotificationListener` (WinRT). It requires package identity,
which the unpackaged Electron build lacks.

**Plan.** Spike first: sparse-package identity for the Gateway process, or the
listener in a small packaged helper. Only if identity works: feed toasts into
the journal as untrusted `notifications:*` events, with an app allowlist.

**Done when.** A Teams toast becomes an Island line on the target host; any app
not on the allowlist is ignored.
