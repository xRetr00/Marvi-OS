"""One switch that keeps everything on this machine.

`MARVI_LOCAL_ONLY` did half the job: every *model* call had to be local. But a
model is not the only thing that leaves -- a web search is a query typed to a
search engine, a connected account is a mailbox read over the internet, the
Telegram bridge is a long poll to Telegram's servers, a hosted memory provider
is the user's own memories on somebody else's disk, and an update check tells
GitHub this machine exists.

Privacy mode is the switch for all of it. It is deliberately blunt: on, the
features that reach the network refuse by name and say why, rather than
degrading quietly into something that looks like a bug. `marvi doctor` reports
what is off, so a person who forgot the switch is on does not spend an evening
debugging a search that "stopped working".

What it does *not* do is stop the Smart Room, the workspace, the clipboard, the
browser you drive yourself, or anything else that was already local. Nothing
here is a claim about network traffic Marvi does not initiate -- Windows,
Playwright's Chromium and the user's own programs are not Marvi's to switch off.
"""

from __future__ import annotations

import os

SETTING = "MARVI_PRIVACY_MODE"

#: What each feature is called when it refuses, in the user's words.
FEATURES = {
    "web": "web search and page fetching",
    "accounts": "connected accounts",
    "telegram": "the Telegram bridge",
    "memory_provider": "hosted memory providers",
    "updates": "update checks",
    "models": "cloud models",
}


#: Which tools reach the network, by name or prefix, and what to call them.
#:
#: A list rather than a guess: a tool that talks to the world is a decision
#: somebody made when they wrote it, and reading it off the name would block
#: `web_search` and miss `send_email`. An MCP server's tools are not here --
#: they are a person's own installed processes, and Marvi does not know what
#: they do; `marvi doctor` says as much rather than implying otherwise.
NETWORKED: dict[str, str] = {
    "web_search": "web",
    "web_extract": "web",
    "web_fetch": "web",
    "accounts_status": "accounts",
    "account_tool_search": "accounts",
    "account_tool_execute": "accounts",
    "calendar_events": "accounts",
    "calendar_add": "accounts",
    "calendar_move": "accounts",
    "calendar_remove": "accounts",
    "email_recent": "accounts",
    "send_email": "accounts",
    "telegram_send": "telegram",
    "telegram_status": "telegram",
    "telegram_recent": "telegram",
}


def on() -> bool:
    return os.environ.get(SETTING, "").strip().lower() in ("1", "true", "yes", "on")


def feature_of(tool: str) -> str:
    """Which switched-off feature this tool belongs to, or "" when it is local."""
    return NETWORKED.get(tool, "")


def refusal(feature: str) -> str:
    """The sentence a refused feature gives back. Names the switch, always."""
    what = FEATURES.get(feature, feature)
    return (
        f"Privacy mode is on, so {what} is switched off. "
        "Turn it off in Settings > Preferences to use this again."
    )


def blocked(feature: str) -> dict[str, str]:
    """A tool result for something privacy mode will not do."""
    return {"error": refusal(feature), "privacy_mode": "on"}
