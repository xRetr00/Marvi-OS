# Backlog — small

A day or less each. Eight of the ten were built on 2026-09-16; the two that are
left are left for a stated reason, not for lack of time.

| # | Item | State |
|---:|---|---|
| S1 | Paste an image into the chat box | done |
| S2 | `@file` and `@url` in the chat box | done |
| S3 | Clipboard images | done |
| S4 | What is playing, and exact volume | volume done; now-playing blocked |
| S5 | Shortcuts in Settings | done, as the shortcuts window |
| S6 | Push-to-talk hold | blocked — see below |
| S7 | File changes on the Activity page | done |
| S8 | Scheduled Obsidian export | done |
| S9 | Export a chat thread | done |
| S10 | Read Windows notifications | blocked — see below |

## Done

### S1. Paste an image into the chat box

`Ctrl+V` of a screenshot attaches it. Windows puts a clipboard image on the
wire as a file with an empty name, which the attachment list showed as a blank
row, so an unnamed image is named for the moment it was taken
(`pasted-2026-09-16T08-30-05.png`) and keeps its own format. Text pastes are
untouched — the textarea owns those.

`renderer/src/chat/paste.ts`, `ui/Composer.tsx`. Tests: `paste.test.ts`.

### S2. `@file` and `@url` in the chat box

`@notes.md` attaches the file; `@https://…` fetches the page and attaches its
text. A mention becomes an ordinary attachment row, so validation, the provider
shape, the attachment chips, the Markdown export and `chat_search` all keep
working with no second path. Content arrives inside the untrusted envelope: `@`
is not a way to put instructions in front of the model. A mention that cannot
be read is told to Marvi, so she says so in her reply rather than ignoring it.
Typing `@` suggests workspace files (trailing mention only; the Gateway
resolves whatever is actually sent).

`marvi_gateway/mentions.py`, `chat.py`; `chat/mention.ts`,
`components/MentionSuggestions.tsx`. Tests: `test_mentions.py`,
`mention.test.ts`.

### S3. Clipboard images

`clipboard_read` falls through to a copied picture: `CF_DIB` is given back its
missing 14-byte header, Pillow converts it, and the vision role answers in
words — the same trade `read_screen` makes, because the voice model usually
cannot take an image at all. Verified on the dev host with a real copied
bitmap.

`marvi_gateway/desk.py`. Tests: `test_desk.py`.

### S4a. Exact volume

`media_status` reads the speaker level and mute state; `media_control` with
`action=volume_set, level=0..100` sets it. Core Audio through `ctypes` — three
COM interfaces called by vtable index — rather than adding `pycaw` and
`comtypes` for forty lines. Verified on the dev host: read 26, set 42, read
back 42, restored to 26.

`marvi_gateway/desk.py`. Tests: `test_desk.py`.

### S5. Shortcuts in Settings

Settings → Preferences → Keyboard shortcuts opens the same window the title-bar
key opens. Better than the planned single field: every shortcut is listed and
editable in one place. See the hotkeys entry in `docs/UI.md`.

### S7. File changes on the Activity page

A "Files Marvi changed" panel lists recent checkpoints with a Restore button.
Restore here is the *user's* action, not the model's, so it raises no
confirmation — pressing the button is the confirmation — and it is audited and
guarded by the local token like every other direct action.

`GET /checkpoints`, `POST /checkpoints/{id}/restore`;
`components/activity-page.tsx`. Tests: `test_checkpoints.py`.

### S8. Scheduled Obsidian export

`export_memory` is a cron action; the job's message is the folder. No second
implementation — it calls the same `vault.export` the CLI does.

`marvi_gateway/schedule.py`. Tests: `test_vault.py`.

### S9. Export a chat thread

The thread list gains a download button: the Gateway renders the visible branch
as Markdown (sources and attachments listed under the message that carried
them) and Electron shows the native save dialog.

`GET /chat/threads/{id}/export`; `chat/components/Sessions.tsx`. Tests:
`test_chat_search.py`.

## Blocked, and what would unblock them

### S6. Push-to-talk hold

Electron's `globalShortcut` has no key-up event, so "hold to talk" cannot be
built from it: the accelerator fires once on press and Marvi never learns when
the key came back up. The options, none of them a day's work:

1. A low-level keyboard hook (`WH_KEYBOARD_LL`) in the existing Rust wake-host,
   reporting key-down and key-up over its newline protocol. No new dependency,
   but it is a new always-running hook on every keystroke on the machine, which
   deserves its own review.
2. `uiohook-napi` (MIT) in Electron main: a native module that must be rebuilt
   per Electron ABI and would join the packaging path.

Until then the summon hotkey is press-to-start; Stop (`Alt+Shift+S`) ends the
session, which covers the same ground in two presses.

### S10. Read Windows notifications

`UserNotificationListener` is the only supported way to read other apps'
toasts, and it needs two things Marvi does not have: the WinRT projection
(`winrt-Windows.UI.Notifications*`, a new dependency) and **package identity** —
an unpackaged Electron/Python process cannot request listener access at all.
That means either a sparse package identity for the Gateway process or a small
packaged helper, plus a user consent prompt in Windows settings. It is a phase,
not a small item; the honest place for it is `big.md` once someone wants it
enough to pay for the packaging work.

Nothing was attempted for either: a half-built keyboard hook or an unpackaged
listener that silently returns nothing is worse than a documented gap.

### S4b. What is playing

Title and artist come from `GlobalSystemMediaTransportControlsSessionManager`,
which is WinRT-only — the same missing projection as S10, though without the
package-identity problem. One dependency (`winrt-Windows.Media.Control`) would
do it; it was not added for a single read-only convenience while the volume
half needed none.
