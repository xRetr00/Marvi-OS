<!--
name: "Tool: telegram_send"
description: "Send the user a Telegram message, optionally with a file from the workspace."
-->
Send the user a message on Telegram — their own linked chat with you, nobody else. Use it
when they ask to be sent something ("text me the list", "send that file to my phone") or when
a finished job should reach them away from the computer. Only the linked owner can receive
it. `file` is a workspace path to attach; leave it empty for text only. Do not use it to
answer a message that already arrived over Telegram — your reply goes there anyway.
