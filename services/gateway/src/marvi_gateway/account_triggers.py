"""Realtime Composio triggers entering ARC through one untrusted boundary."""

from __future__ import annotations

import json
import os
import threading
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from .accounts import ComposioAccounts, _as_dict
from .logs import get_logger
from .untrusted import wrap_external

log = get_logger("memory")


class AccountTriggerIngest:
    """Own the local realtime subscription and signed-webhook ingestion path."""

    def __init__(self, accounts: ComposioAccounts, memory: Any, journal: Any, sync: Any) -> None:
        self.accounts = accounts
        self.memory = memory
        self.journal = journal
        self.sync = sync
        self._subscription: Any = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.connected = False
        self.last_event_at: str | None = None
        self.last_error = ""
        self.received = 0

    @staticmethod
    def _value(event: dict[str, Any], *paths: str) -> Any:
        for path in paths:
            value: Any = event
            for part in path.split("."):
                if not isinstance(value, dict):
                    value = None
                    break
                value = value.get(part)
            if value not in (None, ""):
                return value
        return None

    def ingest(self, raw: Any) -> dict[str, Any]:
        event = _as_dict(raw)
        if not isinstance(event, dict):
            raise ValueError("trigger payload must be an object")
        user_id = str(self._value(event, "user_id", "metadata.connected_account.user_id") or "")
        if user_id and user_id != self.accounts.user_id:
            raise ValueError("trigger belongs to a different Composio user")

        toolkit = str(
            self._value(event, "toolkit_slug", "metadata.toolkit_slug", "data.toolkit.slug") or "unknown"
        ).lower()
        trigger = str(
            self._value(event, "trigger_slug", "metadata.trigger_slug", "data.trigger_slug", "type")
            or "event"
        )
        connection_id = str(
            self._value(event, "metadata.connected_account.id", "connected_account_id", "data.connected_account_id")
            or ""
        )
        event_id = str(
            self._value(event, "uuid", "id", "metadata.uuid", "data.id")
            or f"{toolkit}:{trigger}:{datetime.now(UTC).isoformat()}"
        )
        payload = self._value(event, "payload", "data", "original_payload") or event
        log.info(
            "account trigger received",
            extra={
                "marvi_event_id": event_id,
                "marvi_toolkit": toolkit,
                "marvi_trigger": trigger,
                "marvi_connection_id": connection_id,
            },
        )
        envelope = wrap_external(f"composio:trigger:{toolkit}:{trigger}", payload).model_dump()
        summary = f"{toolkit}: {trigger.replace('_', ' ').lower()}"
        source = f"composio:trigger:{toolkit}:{event_id}"

        journal_id = self.journal.append(
            f"accounts:{toolkit}",
            "trigger",
            summary,
            {
                "id": event_id,
                "provider_id": event_id,
                "toolkit": toolkit,
                "trigger": trigger,
                "connection_id": connection_id,
                "external": envelope,
            },
            trusted=False,
        )
        if journal_id is not None:
            self.memory.remember_external(
                summary,
                json.dumps(payload, ensure_ascii=False, default=str)[:8_000],
                source=source,
            )
            if connection_id:
                # Same ledger AccountIngest's polled fetch writes to, so a
                # trigger-sourced memory is retractable by connection at
                # disconnect exactly like a polled one — see
                # AccountIngest.retract_connection.
                self.sync.store.mark_seen(toolkit, connection_id, source)
        else:
            log.info(
                "account trigger deduplicated",
                extra={"marvi_event_id": event_id, "marvi_toolkit": toolkit},
            )
        sync_result = None
        if self.sync.registry.get(toolkit) is not None:
            sync_result = self.sync.sync_connection(toolkit, connection_id)
        self.received += 1
        self.last_event_at = datetime.now(UTC).isoformat()
        self.last_error = ""
        log.info(
            "account trigger ingested",
            extra={
                "marvi_event_id": event_id,
                "marvi_toolkit": toolkit,
                "marvi_journal_id": journal_id or 0,
                "marvi_sync_started": sync_result is not None,
            },
        )
        return {
            "accepted": True,
            "journal_id": journal_id,
            "toolkit": toolkit,
            "trigger": trigger,
            "sync": sync_result,
        }

    def parse_webhook(self, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
        secret = (os.environ.get("COMPOSIO_WEBHOOK_SECRET") or "").strip()
        if not secret:
            raise RuntimeError("COMPOSIO_WEBHOOK_SECRET is not configured")
        parsed = self.accounts._sdk().triggers.parse(
            body=body, headers=headers, verify_secret=secret
        )
        value = _as_dict(parsed)
        if isinstance(value, dict) and isinstance(value.get("payload"), dict):
            value = value["payload"]
        return self.ingest(value)

    #: How long to wait after a failed subscribe, and the ceiling it backs off
    #: to. It used to be a flat five seconds against a fifteen-second connect
    #: timeout: a Composio account whose trigger stream will not establish
    #: produced a full traceback every twenty seconds, forever. Twelve hours of
    #: that is what filled `errors.log` to 2.8MB and made a Gateway that was
    #: running perfectly look like one crashing in a loop.
    RETRY_START = 5.0
    RETRY_MAX = 300.0

    def _run(self) -> None:
        wait = self.RETRY_START
        told = ""
        while not self._stop.is_set():
            try:
                subscription = self.accounts._sdk().triggers.subscribe(timeout=15.0)
                self._subscription = subscription

                @subscription.handle(user_id=self.accounts.user_id)
                def on_event(event: Any) -> None:
                    try:
                        self.ingest(event)
                    except Exception as exc:  # one malformed event cannot end the stream
                        self.last_error = str(exc)[:300]

                self.connected = True
                self.last_error = ""
                wait = self.RETRY_START
                told = ""
                log.info("Composio trigger stream connected")
                subscription.wait_forever()
            except Exception as exc:
                self.last_error = str(exc)[:300]
                # The traceback once per distinct failure, then the same
                # failure at info without one. A stack that repeats every
                # twenty seconds is not evidence, it is weather -- and it
                # buries the one traceback that is.
                if str(exc)[:240] != told:
                    told = str(exc)[:240]
                    log.warning(
                        "Composio trigger stream failed",
                        extra={"marvi_error": told},
                        exc_info=True,
                    )
                else:
                    log.info(
                        "Composio trigger stream still failing; retrying in %.0fs", wait
                    )
            finally:
                self.connected = False
                self._subscription = None
            if not self._stop.wait(wait):
                # Backed off, because the usual cause is an account that will
                # not connect at all and retrying it hard helps nobody.
                wait = min(self.RETRY_MAX, wait * 2)
                continue

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="marvi-composio-triggers", daemon=True
        )
        self._thread.start()
        log.info("Composio trigger listener started")
        return True

    def stop(self) -> None:
        self._stop.set()
        subscription = self._subscription
        if subscription is not None:
            with suppress(Exception):
                subscription.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        log.info("Composio trigger listener stopped")

    def health(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "received": self.received,
            "last_event_at": self.last_event_at,
            "last_error": self.last_error,
            "transport": "composio-realtime",
        }
