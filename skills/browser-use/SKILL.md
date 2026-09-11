---
name: browser-use
description: How the embedded browser is driven - profiles, reading pages, clicking, forms, tabs, downloads, and handing the keyboard back for a login. Opening one page is yours with browser_open; anything that takes several steps on a site - signing in, filling a form, buying, booking, downloading - goes to Talos with delegate(agent="talos"). Read this when asked how the browser works, or when a browser tool refuses or a session will not open. Not for reading a page you already have, for the desktop or other applications, or for a plain web search.
license: MIT
metadata:
  author: Marvi OS
  version: "1.0"
---

# Using the browser

**In a conversation, Talos does the stepping.** Opening one page is yours with
`browser_open`; anything that takes several actions on a site goes to
`delegate(agent="talos", ...)` while you keep talking. What follows is how the
work is done.

The browser is a real, visible Chromium with saved profiles. The user can see
it and can take it over. You are one of two people holding the mouse.

For a question the web can answer, search first. Open a browser when the task
needs *this* site, *this* account, or an action rather than an answer.

## The loop

1. `browser_open` — returns a receipt, not a browser.
2. `browser_status` — until `state` is `ready`. Take `session_id`, `revision`
   and an exact `tab_id` from it.
3. `browser_action` — with those three, plus a fresh `action_id`.
4. `browser_status` again — to see what actually happened.

**`revision` changes on every state change.** A stale one is refused. Read
status again rather than reusing the number you have.

**An accepted receipt is not success.** `browser_action` returning without an
error means the command was dispatched. Whether the page did the thing is a
question only the next `browser_status` answers. Say what you saw, not what
you asked for.

## Acting on a page

`read` first. You cannot click what you have not observed.

Actions: `read`, `navigate`, `new_tab`, `click`, `fill`, `select`, `press`,
`scroll`, `back`, `forward`, `reload`, `close_tab`, `dialog`, `screenshot`,
`upload`.

Target by the `role` and `name` you saw in the observation, or by `selector`.
It must match **exactly one** element — "Use an unambiguous observed role/name
or selector" means your target matched none or several, not that the page is
broken. Read again and pick a more specific one.

`browser_read_image` answers a question about a tab using Vision, for pages
that read badly as text. Editable fields come back masked.

## Passwords are not yours to type

`fill` refuses password, current-password, new-password and one-time-code
fields. That is deliberate and there is no way around it.

When a login is needed:

1. `browser_control` with `private` — this pauses you and hides the page.
2. Tell the user the browser is theirs and what to sign into.
3. Wait. Do not poll the page; you cannot see it.
4. They resume. Then `read` to find out where you ended up.

Never ask the user to tell you a password, a code, or a card number so you can
type it. Ask them to type it.

## The other controls

`pause` and `stop` end automation and leave the browser open. `resume` starts
a fresh read. `close` ends the session. `show` brings the window forward — use
it when you need the user to look at something.

One browser per profile. "This profile already has a browser" names the
session; use that one or close it.

## Before something irreversible

Purchases, messages, posts, uploads, anything that spends money or reaches
another person: set `request_confirmation=true` and let the user decide. You
choose when to ask; the Gateway only checks that you did.

If one of those times out, **inspect — never retry blind.** A submitted order
that did not answer may still be an order. Say the outcome is unknown and go
and look.

## When it will not open

The failure names the step. "That address was refused" is a bad URL, not a
broken browser; "the browser engine did not start" is Setup. Read the message
before restarting anything.

`browser_read`, `browser_click`, `browser_type`, `browser_back`,
`browser_links`, `browser_screenshot` and `browser_close` are dead names kept
so old prompts fail loudly. They execute nothing. Use `browser_action`.
