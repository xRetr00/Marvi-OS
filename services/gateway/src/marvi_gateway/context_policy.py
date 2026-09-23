"""User-owned automatic context admission. Explicit tools remain available."""

from __future__ import annotations

import os

SOURCES = ("room", "vision", "weather", "map", "activity", "accounts", "memory",
           "continuity", "system", "skills", "plugins", "mind")
SETTINGS = ("MARVI_MIND_ENABLED", "MARVI_ANNOUNCE", *(
    f"MARVI_CONTEXT_{target}_{source}".upper()
    for target in ("mind", "prompt") for source in SOURCES
))


def enabled(key: str) -> bool:
    return os.environ.get(key, "true").strip().lower() not in ("0", "off", "false")


def mind_enabled() -> bool:
    return enabled("MARVI_MIND_ENABLED")


def allows(source: str, target: str = "prompt") -> bool:
    return enabled(f"MARVI_CONTEXT_{target}_{source}".upper())


def room_allowed(target: str = "prompt") -> bool:
    # The upstream room summary and fused presence include camera and phone
    # facts. Never try to redact opaque prose after it has been composed.
    return all(allows(source, target) for source in ("room", "vision", "map"))


def event_allowed(source: str, kind: str = "") -> bool:
    if not mind_enabled():
        return False
    source = source.lower().split(":", 1)[0]
    if source in ("room", "smart_room"):
        return room_allowed("mind")
    category = {"focus": "activity", "machine": "system", "curiosity": "mind",
                "telegram": "accounts", "schedule": "mind", "location": "map"}.get(source, source)
    if category not in SOURCES:
        category = "plugins"
    if category == "weather" and not allows("map", "mind"):
        return False
    return allows(category, "mind")


def visible() -> dict[str, str]:
    return {key: str(enabled(key)).lower() for key in SETTINGS}
