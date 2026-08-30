"""Composio's calendar payload as the few fields a card can draw.

The tool path hands the model an `[EXTERNAL DATA ...]` envelope wrapped round
whatever Google returned, which is right for a model reading somebody's
calendar and wrong for a page drawing it: a card does not obey instructions, it
lays out rectangles, and it needs a title and a time rather than four hundred
lines of JSON with a boundary marker on top.

So this is the same data, flattened, and nothing else. No formatting, no
timezone maths, no "in 20 minutes" -- those belong to the renderer, which knows
the user's clock and the width it has to fit in.
"""

from __future__ import annotations

from typing import Any


def _at(when: Any) -> str:
    """A Google start/end, which is `dateTime` for a meeting and `date` for a
    whole day, as one string the renderer can parse."""
    if isinstance(when, dict):
        return str(when.get("dateTime") or when.get("date") or "")
    return str(when or "")


def _items(payload: Any) -> list[dict[str, Any]]:
    """Google's event list, wherever this Composio version happens to put it."""
    if isinstance(payload, dict):
        for key in ("items", "events", "data", "response_data", "result"):
            found = payload.get(key)
            if isinstance(found, list):
                return [row for row in found if isinstance(row, dict)]
            if isinstance(found, dict):
                deeper = _items(found)
                if deeper:
                    return deeper
    return []


def upcoming(payload: Any, limit: int = 8) -> list[dict[str, Any]]:
    """The next few events, oldest first, as flat rows."""
    rows = []
    for item in _items(payload)[: max(1, limit)]:
        start = _at(item.get("start"))
        if not start:
            continue
        rows.append(
            {
                "id": str(item.get("id") or ""),
                # Google omits the summary for events the user has no read
                # access to the details of, and "(busy)" is what the calendar
                # itself shows in that case.
                "title": str(item.get("summary") or "(busy)")[:120],
                "start": start,
                "end": _at(item.get("end")),
                "location": str(item.get("location") or "")[:80],
                # A date without a time is Google's way of saying all day, and
                # the card draws those differently.
                "all_day": "T" not in start,
            }
        )
    rows.sort(key=lambda row: row["start"])
    return rows
