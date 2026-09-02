"""Which accounts are actually connected, for the prompt.

Every other part of Marvi's own shape reaches her: the tools by name, the
skills by name and trigger, memory as a standing brief, the room through its
component status. The accounts did not. Six were connected on this machine --
GitHub, Gmail, Google Calendar, Drive, Notion, YouTube -- one was expired and
one disconnected, and none of that appeared anywhere in the request.

The tools were there. `email_recent`, `calendar_events` and `accounts_status`
all ship in the catalogue. What was missing is the runtime half: a tool that
exists is not a tool that will work, because whether Gmail answers depends on
a connection made months ago in a settings page. Without that, "can you check
my email" is answerable only by calling something and finding out -- and the
recorded failure is her not calling it: *"you have no connected accounts"*,
said to somebody with six.

This is the distinction the context-engineering literature draws between
static instruction and runtime state, and accounts are as runtime as state
gets: they expire, they get revoked, they are added while she is running.

## Why the expired ones are named too

A connector that is expired is worse than one that was never set up, because
the tool is right there and fails. Saying so lets her tell somebody their
Reddit needs reconnecting instead of reporting a tool error they cannot act on.

## Why this is short

It is paid on every turn. Names and one word of state each -- no descriptions,
no capability lists, no advice about what to do with them. The tools already
say what can be done; this says only which of them will answer.
"""

from __future__ import annotations

from typing import Any

#: Beyond this many, the list stops being a fact and starts being a page.
MOST = 24


def describe(rows: list[dict[str, Any]]) -> str:
    """The prompt block, or "" when there is nothing worth saying.

    `rows` are `accounts.cached_connections()` shaped -- each with a `toolkit`
    and a `connected` flag, and optionally a `status`.
    """
    connected: list[str] = []
    broken: list[str] = []
    for row in rows:
        toolkit = str(row.get("toolkit") or "").strip().lower()
        if not toolkit:
            continue
        if row.get("connected"):
            if toolkit not in connected:
                connected.append(toolkit)
        elif toolkit not in broken:
            broken.append(toolkit)
    # A toolkit with one working connection and one stale one is working.
    broken = [name for name in broken if name not in connected]
    if not connected and not broken:
        return ""

    lines = ["# Accounts that are connected"]
    if connected:
        lines.append(
            "These answer right now: " + ", ".join(sorted(connected)[:MOST]) + "."
        )
    if broken:
        # Named as needing the user, because that is the only way it gets
        # fixed and she cannot do it herself.
        lines.append(
            "These are set up but not working and need reconnecting in "
            "Settings, so say that rather than reporting a tool failure: "
            + ", ".join(sorted(broken)[:MOST])
            + "."
        )
    if not connected:
        lines.append("Nothing else is connected, so account tools will not answer.")
    return "\n".join(lines)
