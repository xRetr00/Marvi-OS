<!--
name: "Tool: browser_action"
description: "Act in a ready browser session."
-->
Act in a ready browser session. Use its current revision and an exact tab_id. Actions:
read, navigate, new_tab, click, fill, select, press, scroll, back, forward, reload,
close_tab, dialog, screenshot, upload. arguments contains tab_id and observed role/name
or selector; url/text/value/key/pixels/path as needed. Never enter passwords or OTPs:
use browser_control private and ask the user to sign in. Decide if approval is needed
and set request_confirmation=true. Use a unique action_id; reuse it only for transport
retries. Read browser_status to verify completion, never claim an accepted receipt is
success.
