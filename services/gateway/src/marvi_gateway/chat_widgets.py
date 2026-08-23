"""Validated, replayable UI parts for Chat.

Widgets are data, never executable renderer instructions. The model and tools
may choose from this finite vocabulary; the Gateway validates and caps every
field before a part is persisted or streamed.
"""

from __future__ import annotations

import ipaddress
import json
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

WIDGET_KINDS = (
    "sources",
    "metrics",
    "comparison",
    "table",
    "timeline",
    "weather",
    "gallery",
    "document",
    "status",
)
MAX_ITEMS = 50
MAX_COLUMNS = 12
MAX_TEXT = 2_000


def present_tool_schema() -> dict[str, Any]:
    """The display-only tool exposed to Chat models."""
    return {
        "name": "present_widget",
        "description": (
            "Present structured information as a Marvi UI widget. Use it for comparisons, "
            "tables, metrics, timelines, weather, documents, galleries, sources, or progress; "
            "do not use it for ordinary prose. This only displays data and performs no action."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(WIDGET_KINDS)},
                "title": {"type": "string", "maxLength": 120},
                "data": {"type": "object"},
            },
            "required": ["kind", "title", "data"],
            "additionalProperties": False,
        },
    }


def validate_widget(arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ValueError("widget arguments must be an object")
    kind = str(arguments.get("kind") or "").strip().lower()
    if kind not in WIDGET_KINDS:
        raise ValueError("unknown widget kind")
    title = _text(arguments.get("title"), 120) or kind.replace("_", " ").title()
    data = arguments.get("data")
    if not isinstance(data, dict):
        raise ValueError("widget data must be an object")
    clean = _VALIDATORS[kind](data)
    return {
        "type": "widget",
        "id": uuid4().hex,
        "version": 1,
        "kind": kind,
        "title": title,
        "status": "complete",
        "data": clean,
    }


def widget_for_tool(name: str, result: Any) -> dict[str, Any] | None:
    """Turn known structured tool evidence into a deterministic widget."""
    payload = external_payload(result)
    if name == "web_search" and isinstance(payload, list):
        items = []
        for row in payload[:MAX_ITEMS]:
            if not isinstance(row, dict) or not _public_url(row.get("url")):
                continue
            items.append(
                {
                    "title": _text(row.get("title"), 200) or "Untitled result",
                    "url": str(row["url"]),
                    "snippet": _text(row.get("snippet") or row.get("description"), 500),
                }
            )
        if items:
            return validate_widget(
                {"kind": "sources", "title": "Web evidence", "data": {"items": items}}
            )
    if name == "web_extract" and isinstance(payload, dict):
        url = payload.get("url")
        return validate_widget(
            {
                "kind": "document",
                "title": _text(payload.get("title"), 120) or "Web document",
                "data": {
                    "name": _text(payload.get("title"), 160) or "Web document",
                    "summary": _text(payload.get("text"), 1_200),
                    "url": str(url) if _public_url(url) else "",
                },
            }
        )
    return None


def source_parts(widget: dict[str, Any]) -> list[dict[str, Any]]:
    if widget.get("kind") != "sources":
        return []
    return [
        {"type": "source", "title": item["title"], "url": item["url"]}
        for item in widget.get("data", {}).get("items", [])
        if isinstance(item, dict) and item.get("url")
    ]


def external_text(result: Any) -> str | None:
    """Reuse a router-owned external envelope instead of nesting it again."""
    if not isinstance(result, dict):
        return None
    text = result.get("text")
    label = result.get("source")
    if (
        isinstance(text, str)
        and isinstance(label, str)
        and text.startswith("[EXTERNAL DATA ")
        and "\n[END EXTERNAL DATA " in text
    ):
        return text
    return None


def external_payload(result: Any) -> Any:
    if not isinstance(result, dict) or not isinstance(result.get("text"), str):
        return result
    text = result["text"]
    first = text.find("\n")
    last = text.rfind("\n[END EXTERNAL DATA ")
    if first < 0 or last <= first:
        return result
    try:
        return json.loads(text[first + 1 : last])
    except (TypeError, ValueError):
        return text[first + 1 : last]


def _text(value: Any, limit: int = MAX_TEXT) -> str:
    return " ".join(str(value or "").split())[:limit]


def _public_url(value: Any) -> bool:
    try:
        parsed = urlsplit(str(value))
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not host or parsed.username:
        return False
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True


def _items(data: dict[str, Any], keys: tuple[str, ...], limit: int = MAX_ITEMS) -> list[dict[str, str]]:
    clean: list[dict[str, str]] = []
    rows = data.get("items")
    if not isinstance(rows, list):
        raise ValueError("widget items must be a list")
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        item = {key: _text(row.get(key), 500) for key in keys}
        if any(item.values()):
            clean.append(item)
    if not clean:
        raise ValueError("widget needs at least one item")
    return clean


def _sources(data: dict[str, Any]) -> dict[str, Any]:
    rows = _items(data, ("title", "url", "snippet"))
    rows = [row for row in rows if _public_url(row["url"])]
    if not rows:
        raise ValueError("source widget needs a public URL")
    return {"items": rows}


def _metrics(data: dict[str, Any]) -> dict[str, Any]:
    return {"items": _items(data, ("label", "value", "detail"), 12)}


def _comparison(data: dict[str, Any]) -> dict[str, Any]:
    return {"items": _items(data, ("label", "value", "detail"), 16)}


def _table(data: dict[str, Any]) -> dict[str, Any]:
    columns = data.get("columns")
    rows = data.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ValueError("table needs columns and rows")
    clean_columns = [_text(column, 80) for column in columns[:MAX_COLUMNS] if _text(column, 80)]
    if not clean_columns:
        raise ValueError("table needs at least one column")
    clean_rows = []
    for row in rows[:MAX_ITEMS]:
        if isinstance(row, list):
            clean_rows.append([_text(value, 300) for value in row[: len(clean_columns)]])
    return {"columns": clean_columns, "rows": clean_rows}


def _timeline(data: dict[str, Any]) -> dict[str, Any]:
    return {"items": _items(data, ("at", "label", "detail", "status"), 24)}


def _weather(data: dict[str, Any]) -> dict[str, Any]:
    return {key: _text(data.get(key), 200) for key in ("location", "temperature", "condition", "detail")}


def _gallery(data: dict[str, Any]) -> dict[str, Any]:
    rows = _items(data, ("url", "attachment_id", "alt"), 12)
    return {
        "items": [
            row for row in rows if row.get("attachment_id") or _public_url(row.get("url"))
        ]
    }


def _document(data: dict[str, Any]) -> dict[str, Any]:
    url = data.get("url")
    return {
        "name": _text(data.get("name"), 160),
        "summary": _text(data.get("summary"), 1_200),
        "url": str(url) if _public_url(url) else "",
    }


def _status(data: dict[str, Any]) -> dict[str, Any]:
    return {"items": _items(data, ("label", "detail", "status"), 24)}


_VALIDATORS = {
    "sources": _sources,
    "metrics": _metrics,
    "comparison": _comparison,
    "table": _table,
    "timeline": _timeline,
    "weather": _weather,
    "gallery": _gallery,
    "document": _document,
    "status": _status,
}
