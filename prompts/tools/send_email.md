<!--
name: "Tool: send_email"
description: "Send an email from the user's connected account."
-->
Send an email from the user's connected account. This leaves the machine and cannot be
undone -- there is no unsend. Confirm recipient, subject and gist with the user before
calling it. Never call it twice for one request: if it fails partway, check with
email_recent rather than sending again, because a retry can deliver two. Never put a
password, code or card number in a message.
