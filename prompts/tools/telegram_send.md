<!--
name: "Tool: telegram_send"
description: "Send the user a Telegram message, optionally with files or photos."
-->
Send the user a message on Telegram — their own linked chat with you, nobody else. Use it
when they ask to be sent something ("text me the list", "send those photos to my phone") or
when a finished job should reach them away from the computer.

Attach with `file` (one path) or `files` (up to 10 paths). Photos arrive as an album that
previews inline; other files arrive as documents. A folder path sends its newest photos, or
its newest files if it has no photos — so "send me today's visitor photos" is one call with
the folder. `text` becomes the caption. The result lists what was sent and says if older
files were left out; tell the user when that happens.

Do not use it to answer a message that already arrived over Telegram — your reply goes
there anyway, but files still need this tool.
