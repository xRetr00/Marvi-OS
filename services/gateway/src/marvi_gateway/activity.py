"""Desktop activity as world context.

ActivityWatch already runs locally and knows which window has focus, whether
the machine is idle, and — via its browser watcher — which tab is in front. It
does not see inside an application, and this adapter does not pretend
otherwise: it reports the window, which is genuinely useful context for "is now
a good moment to interrupt".

One thing worth being careful about: a window title is not trustworthy input.
A browser tab's title is set by the page, so any website can choose what
appears here. Titles are therefore treated as external content and enveloped
like anything else off the network.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import httpx

from .untrusted import wrap_external

DEFAULT_URL = "http://127.0.0.1:5600"
REQUEST_TIMEOUT = 3.0
IDLE_AFTER_SECONDS = 300


def activity_url() -> str:
    return os.environ.get("MARVI_ACTIVITYWATCH_URL", DEFAULT_URL).rstrip("/")


class ActivityWatch:
    """Read-only client. Marvi never writes to the activity log."""

    def __init__(self, base_url: str | None = None, client: httpx.Client | None = None) -> None:
        self.base_url = (base_url or activity_url()).rstrip("/")
        self._client = client

    def _http(self) -> httpx.Client:
        return self._client or httpx.Client(timeout=REQUEST_TIMEOUT)

    def _close(self, client: httpx.Client) -> None:
        if self._client is None:
            client.close()

    def available(self) -> bool:
        client = self._http()
        try:
            return client.get(f"{self.base_url}/api/0/buckets/").status_code == 200
        except httpx.HTTPError:
            return False
        finally:
            self._close(client)

    def buckets(self) -> dict[str, Any]:
        client = self._http()
        try:
            response = client.get(f"{self.base_url}/api/0/buckets/")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError:
            return {}
        finally:
            self._close(client)

    def _latest(self, bucket_type: str, limit: int = 1) -> list[dict[str, Any]]:
        wanted = [k for k, v in self.buckets().items() if v.get("type") == bucket_type]
        if not wanted:
            return []
        client = self._http()
        events: list[dict[str, Any]] = []
        try:
            for bucket in wanted:
                response = client.get(
                    f"{self.base_url}/api/0/buckets/{bucket}/events", params={"limit": limit}
                )
                if response.status_code == 200:
                    events.extend(response.json() or [])
        except httpx.HTTPError:
            return []
        finally:
            self._close(client)
        events.sort(key=lambda e: str(e.get("timestamp", "")), reverse=True)
        return events[:limit]

    # -- the three questions worth asking ------------------------------------

    def current_window(self) -> dict[str, Any] | None:
        events = self._latest("currentwindow")
        if not events:
            return None
        data = events[0].get("data") or {}
        return {
            "app": str(data.get("app", ""))[:120],
            "title": str(data.get("title", ""))[:200],
            "at": events[0].get("timestamp"),
        }

    def current_tab(self) -> dict[str, Any] | None:
        events = self._latest("web.tab.current")
        if not events:
            return None
        data = events[0].get("data") or {}
        return {
            "url": str(data.get("url", ""))[:300],
            "title": str(data.get("title", ""))[:200],
            "at": events[0].get("timestamp"),
        }

    def idle(self) -> bool | None:
        """True when the machine reports the user away."""
        events = self._latest("afkstatus")
        if not events:
            return None
        status = str((events[0].get("data") or {}).get("status", "")).lower()
        if status == "afk":
            return True
        if status == "not-afk":
            # A stale not-afk reading is not evidence of presence.
            stamp = str(events[0].get("timestamp", ""))
            try:
                seen = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                return False
            return (datetime.now(UTC) - seen).total_seconds() > IDLE_AFTER_SECONDS
        return None

    def today(self, limit: int = 400) -> list[dict[str, Any]]:
        """Which applications were used today, longest first.

        The adapter could only ever answer "what is in front of you right
        now" -- one window, this instant. That is enough to decide whether to
        interrupt and useless for "what have I been doing today", which is the
        question a person actually asks an assistant.

        Durations are summed per application from the window bucket, so a
        morning spent moving between two editors reads as two applications with
        real minutes against them rather than as whichever one happened to be
        focused when the question was asked.

        Titles are deliberately dropped. A window title is set by the
        application and a browser tab's by the page -- untrusted text, and the
        application name is the part that answers the question.
        """
        from collections import defaultdict
        from datetime import UTC, datetime

        events = self._latest("currentwindow", limit=max(1, min(limit, 2000)))
        if not events:
            return []
        start = datetime.now(UTC).astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        seconds: dict[str, float] = defaultdict(float)
        for event in events:
            stamp = str(event.get("timestamp") or "")
            try:
                when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                continue
            if when.astimezone() < start:
                continue
            app = str((event.get("data") or {}).get("app") or "").strip()
            if not app:
                continue
            seconds[app] += float(event.get("duration") or 0.0)
        ranked = sorted(seconds.items(), key=lambda pair: -pair[1])
        return [
            {"app": app, "seconds": round(total, 1), "minutes": round(total / 60.0, 1)}
            for app, total in ranked
            if total > 0
        ]

    def used_today(self, most: int = 5) -> list[str]:
        """Just the names, for the prompt. Longest-used first."""
        return [row["app"] for row in self.today()[:most]]

    def world_context(self) -> dict[str, Any]:
        """A compact picture of what the machine's user is doing right now."""
        window = self.current_window()
        tab = self.current_tab()
        idle = self.idle()
        parts = []
        if idle:
            parts.append("away from the machine")
        elif window:
            parts.append(f"in {window['app']}" if window["app"] else "at the machine")
        if tab and tab.get("url"):
            host = tab["url"].split("/")[2] if "://" in tab["url"] else tab["url"]
            parts.append(f"browsing {host[:60]}")
        return {
            "idle": idle,
            "window": window,
            "tab": tab,
            "summary": ", ".join(parts) or "no activity data",
        }


def register_activity_tools(registry, activity: ActivityWatch) -> None:
    from .tools import ToolSpec

    def activity_now() -> dict[str, Any]:
        context = activity.world_context()
        # Window and tab titles are chosen by whatever is being viewed, so a web
        # page can write whatever it likes here. Treat it as external content.
        return wrap_external("activitywatch", context).model_dump()

    def activity_today(_arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Which applications were used today, longest first.

        Application names only, and they come from the window manager rather
        than from any page, so unlike a window title this is not text somebody
        else chose. Wrapped anyway, because it still originates outside Marvi.
        """
        return wrap_external("activitywatch", {"apps": activity.today()}).model_dump()

    registry.register(
        ToolSpec(
            name="activity_now",
            description="Read what the user is doing on this machine",
            arguments={},
            sensitive=False,
            handler=activity_now,
        )
    )
    registry.register(
        ToolSpec(
            name="activity_today",
            description="Which apps the user has spent time in today, longest first",
            arguments={},
            sensitive=False,
            handler=activity_today,
        )
    )
