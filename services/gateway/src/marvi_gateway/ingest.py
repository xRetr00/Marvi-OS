"""Account event ingestion.

Connected accounts are polled on a bounded schedule, normalised into durable
memory entries, and deduplicated by the provider's own id so a poll that
overlaps a previous one cannot double-record anything.

Three rules hold here:

* ingestion never blocks the voice path — it is called from a background tick,
  and a provider outage is a logged no-op rather than an error the user hears;
* everything ingested is stored untrusted, because it is somebody else's
  writing arriving without being asked for;
* a poll that finds nothing new is the normal case and must be cheap.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .accounts import CALENDAR_EVENTS, GMAIL_FETCH, ComposioAccounts

MAX_PER_POLL = 10
SEEN_MARKER_KIND = "episodic"


def _text(value: Any, limit: int = 400) -> str:
    return str(value or "").strip().replace("\r", "")[:limit]


class AccountIngest:
    """Polls connected accounts and records what is new."""

    def __init__(self, accounts: ComposioAccounts, memory: Any) -> None:
        self.accounts = accounts
        self.memory = memory

    # -- deduplication ------------------------------------------------------

    def _already_seen(self, provider_id: str) -> bool:
        row = self.memory._db.execute(
            "SELECT 1 FROM memories WHERE source = ? LIMIT 1", (provider_id,)
        ).fetchone()
        return row is not None

    # -- normalisation ------------------------------------------------------

    @staticmethod
    def normalise_email(message: dict[str, Any]) -> dict[str, Any] | None:
        identifier = message.get("messageId") or message.get("id")
        if not identifier:
            return None
        sender = _text(message.get("sender") or message.get("from"), 160)
        subject = _text(message.get("subject") or "(no subject)", 160)
        body = _text(
            message.get("messageText") or message.get("snippet") or message.get("preview") or "",
            2_000,
        )
        return {
            "provider_id": f"composio:gmail:{identifier}",
            "subject": f"Email: {subject}",
            "body": f"From {sender}\n\n{body}" if sender else body,
            "entities": [e for e in (sender,) if e],
        }

    @staticmethod
    def normalise_calendar(event: dict[str, Any]) -> dict[str, Any] | None:
        identifier = event.get("id")
        if not identifier:
            return None
        summary = _text(event.get("summary") or "(untitled event)", 160)
        start = event.get("start") or {}
        when = _text(start.get("dateTime") or start.get("date") or "", 60)
        return {
            "provider_id": f"composio:googlecalendar:{identifier}",
            "subject": f"Event: {summary}",
            "body": f"Starts {when}" if when else summary,
            "entities": [],
        }

    # -- polling ------------------------------------------------------------

    def _records(self, payload: Any, key: str) -> list[dict[str, Any]]:
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return []
        items = data.get(key) or data.get("items") or data.get("messages") or []
        return [i for i in items if isinstance(i, dict)][:MAX_PER_POLL]

    def poll(self) -> dict[str, Any]:
        """One bounded tick. Never raises: a provider outage is a no-op."""
        ingested: list[str] = []
        skipped = 0
        errors: list[str] = []

        try:
            connected = {row["toolkit"] for row in self.accounts.connections() if row["connected"]}
        except Exception as exc:
            return {"ingested": [], "skipped": 0, "errors": [str(exc)[:160]]}

        sources = []
        if "gmail" in connected:
            sources.append(("gmail", GMAIL_FETCH, {"max_results": MAX_PER_POLL}, "messages", self.normalise_email))
        if "googlecalendar" in connected:
            sources.append((
                "googlecalendar",
                CALENDAR_EVENTS,
                {"calendarId": "primary", "maxResults": MAX_PER_POLL, "singleEvents": True},
                "items",
                self.normalise_calendar,
            ))

        for name, action, arguments, key, normalise in sources:
            try:
                payload = self.accounts.execute(action, arguments)
            except Exception as exc:
                errors.append(f"{name}: {str(exc)[:120]}")
                continue

            for record in self._records(payload, key):
                item = normalise(record)
                if item is None:
                    continue
                if self._already_seen(item["provider_id"]):
                    skipped += 1
                    continue
                self.memory.remember_external(
                    item["subject"], item["body"], source=item["provider_id"]
                )
                for entity in item["entities"]:
                    # Graph edges from untrusted content stay marked untrusted.
                    self.memory.link(
                        entity, "sent", item["subject"], source=item["provider_id"], trusted=False
                    )
                ingested.append(item["subject"])

        return {
            "at": datetime.now(UTC).isoformat(),
            "ingested": ingested,
            "skipped": skipped,
            "errors": errors,
        }
