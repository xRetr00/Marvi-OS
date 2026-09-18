"""Keeping one tool result from eating the conversation.

A web page, a log tail, a long file: any of them can come back larger than
everything else in the turn put together, and every token of it is paid for
again on every subsequent round of the same conversation. On the voice path
that is latency; everywhere it is money.

Three rules, and the second is the one that makes this safe to switch on:

* **Trim the text, never the shape.** Only string values are shortened --
  the keys, the numbers, the lists and the nesting are untouched. A widget
  that reads `result["sources"][0]["url"]` still finds it; a caller that
  branches on `result["ok"]` still gets a boolean.
* **Some tools are never trimmed.** Anything Marvi's own code parses rather
  than reads -- the browser and computer drivers, confirmations, the widget
  tool, sub-agent control -- is left exactly as it was, because a shortened
  field there is a bug rather than a saving.
* **Nothing is lost, for a while.** What was cut is kept in memory under a
  handle, and `tool_more` reads the rest. A model that needs the whole thing
  can still get it; it just has to ask, which is the point.

The size of every result has been recorded since the measurement pass, so the
caps here can be argued with from data rather than from taste.
"""

from __future__ import annotations

import json
import os
import threading
from collections import OrderedDict
from typing import Any

#: The default ceiling for one tool result, in characters. Generous on
#: purpose: this is meant to catch the result that swamps a conversation, not
#: to nibble at ordinary ones.
DEFAULT_CAP = 12_000

SETTING = "MARVI_TOOL_RESULT_CAP"

#: Tools whose results Marvi's own code parses. Trimming a field here breaks a
#: widget or a driver rather than saving anything worth having.
NEVER_TRIMMED = frozenset(
    {
        "present_widget",
        "clarify",
        "ask_secret",
        "delegate",
        "delegate_approve",
        "delegate_steer",
        "delegate_stop",
        "delegated_status",
        "delegate_to_coder",
        "coder_permission",
        "file_checkpoints",
        "media_status",
        "room_state",
        "room_health",
    }
)

#: Prefixes of the same kind: every browser and computer call is a protocol
#: exchange, not prose.
NEVER_TRIMMED_PREFIXES = ("browser_", "computer_")

#: How many trimmed results are kept for `tool_more`. Small: this is a way to
#: finish reading something from a moment ago, not a second store.
KEPT = 12

#: How much one `tool_more` call hands back.
SLICE = 6_000

_lock = threading.Lock()
_kept: OrderedDict[str, str] = OrderedDict()


def cap() -> int:
    """The ceiling, from the environment so it can be argued with at runtime."""
    try:
        wanted = int(os.environ.get(SETTING, "").strip() or DEFAULT_CAP)
    except ValueError:
        return DEFAULT_CAP
    # Zero or negative switches trimming off entirely, which is a legitimate
    # thing to want on a machine with a huge local context window.
    return wanted if wanted > 0 else 0


def trimmable(tool: str) -> bool:
    return tool not in NEVER_TRIMMED and not tool.startswith(NEVER_TRIMMED_PREFIXES)


def _keep(tool: str, whole: str) -> str:
    """Put the full text aside and return the handle that reads it back."""
    handle = f"{tool}-{len(_kept) + 1}-{abs(hash(whole)) % 10_000:04d}"
    with _lock:
        _kept[handle] = whole
        while len(_kept) > KEPT:
            _kept.popitem(last=False)
    return handle


def more(handle: str, offset: int = 0) -> dict[str, Any]:
    """The next slice of something that was trimmed."""
    with _lock:
        whole = _kept.get(handle)
    if whole is None:
        return {
            "error": "that result is no longer available. Run the tool again if you need it.",
        }
    start = max(0, int(offset))
    chunk = whole[start : start + SLICE]
    ends = start + len(chunk)
    return {
        "handle": handle,
        "text": chunk,
        "from": start,
        "to": ends,
        "of": len(whole),
        "more": ends < len(whole),
    }


def _shorten(value: str, budget: int, tool: str, cut: list[int]) -> str:
    if len(value) <= budget:
        return value
    handle = _keep(tool, value)
    cut.append(len(value) - budget)
    return (
        value[:budget]
        + f"\n\n[{len(value) - budget:,} more characters. "
        + f'Read them with tool_more handle="{handle}".]'
    )


def apply(tool: str, result: Any, ceiling: int | None = None) -> tuple[Any, int]:
    """`result`, with any oversized text shortened. Returns it and what was cut.

    The budget is shared across the strings in one result, so a dict of ten
    long fields is not ten times the cap.
    """
    budget = cap() if ceiling is None else ceiling
    if not budget or not trimmable(tool):
        return result, 0
    try:
        size = len(result) if isinstance(result, str) else len(json.dumps(result, default=str))
    except (TypeError, ValueError):
        return result, 0
    if size <= budget:
        return result, 0

    cut: list[int] = []
    if isinstance(result, str):
        return _shorten(result, budget, tool, cut), sum(cut)
    if not isinstance(result, dict):
        return result, 0

    # Longest field first: one huge `text` beside three short ones should lose
    # the huge one, not a share from each.
    strings = sorted(
        ((key, value) for key, value in result.items() if isinstance(value, str)),
        key=lambda pair: len(pair[1]),
        reverse=True,
    )
    if not strings:
        return result, 0
    trimmed = dict(result)
    left = budget
    for index, (key, value) in enumerate(strings):
        share = max(600, left // max(1, len(strings) - index))
        trimmed[key] = _shorten(value, share, tool, cut)
        left = max(0, left - min(len(value), share))
    return trimmed, sum(cut)


def register_more_tool(registry: Any) -> None:
    from .tools import ToolSpec

    def tool_more(handle: str, offset: int = 0) -> dict[str, Any]:
        return more(handle, offset)

    registry.register(
        ToolSpec(
            name="tool_more",
            description="Read the rest of a tool result that was shortened.",
            arguments={"handle": str},
            optional={"offset": int},
            sensitive=False,
            handler=tool_more,
            describes={
                "handle": "The handle printed where the result was cut off.",
                "offset": "Where to read from. Use the `to` of the previous slice.",
            },
        )
    )
