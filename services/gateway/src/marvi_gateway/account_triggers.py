"""Realtime Composio triggers entering Marvi Cortex through one untrusted boundary."""

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


def _rows_of(page: Any) -> list[Any]:
    """The list inside a paged SDK response, whatever it decided to call it."""
    body = _as_dict(page)
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("items", "data", "results", "triggers"):
            found = body.get(key)
            if isinstance(found, list):
                return found
    return []


#: The one trigger worth enabling per toolkit, and what it needs configured.
#:
#: The listener has been subscribing to the delivery stream since it was
#: written -- "Composio trigger stream connected", seven times in one real log
#: -- and nothing anywhere ever *created* a trigger instance. A subscription
#: with no trigger behind it is a correctly-connected socket that is silent
#: forever, which is exactly how it behaved: `received=0`, always, while the
#: ten-minute poll did the work badly.
#:
#: One per toolkit rather than everything on offer. Gmail alone publishes
#: several, and subscribing to all of them is how the mind's token budget gets
#: spent on label changes.
WANTED_TRIGGERS: dict[str, tuple[str, dict[str, Any]]] = {
    "gmail": ("GMAIL_NEW_GMAIL_MESSAGE", {"interval": 1, "labelIds": "INBOX"}),
    "googlecalendar": ("GOOGLECALENDAR_NEW_EVENT_TRIGGER", {}),
    "github": ("GITHUB_COMMIT_EVENT", {}),
    "slack": ("SLACK_RECEIVE_MESSAGE", {}),
}


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

    def _understand(self, toolkit: str, payload: Any) -> Any:
        """The pushed payload as the same `MemoryItem` a poll would produce.

        None when this toolkit has no provider, when the payload is not shaped
        like one of its records, or when the gatekeeper decides it is not worth
        keeping -- and in every one of those cases the caller falls back to the
        old behaviour rather than dropping the event.
        """
        provider = self.sync.registry.get(toolkit)
        if provider is None or not isinstance(payload, dict):
            return None
        try:
            item = provider.normalize(payload)
        except Exception as exc:
            log.info("could not read a pushed %s event (%s)", toolkit, str(exc)[:120])
            return None
        if item is None:
            return None
        cognition = getattr(self.sync, "cognition", None)
        if cognition is None:
            return item
        try:
            from . import gatekeeping

            kept = gatekeeping.worth_keeping(
                cognition, [item], getattr(self.sync, "speaking_to", "")
            )
        except Exception as exc:
            log.info("gatekeeper unavailable for a pushed event (%s); keeping it", str(exc)[:120])
            return item
        # An empty list is the gatekeeper saying this is not worth keeping --
        # a newsletter arriving by push is still a newsletter. The event is
        # still journalled, just without a summary, so it shows and stays quiet.
        return kept[0] if kept else item

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
        source = f"composio:trigger:{toolkit}:{event_id}"

        # Understood the same way a polled item is.
        #
        # This path had its own everything: a summary made out of the trigger
        # slug ("gmail: gmail new gmail message"), a memory body that was the
        # raw JSON, and a journal `kind` of "trigger" -- so the policy looked
        # up `accounts:gmail:trigger`, found nothing, and fell through to the
        # default. A real email arrived by push and was filed as `activity`
        # while the same email arriving by poll was spoken:
        #
        #   06:35  gmail: gmail new gmail message      activity   ceiling activity
        #   05:43  Email: 3 Mailboxes Deleted          speak      Your three Neudocs
        #                                                         mailboxes were deleted...
        #
        # Push and poll are two ways of finding out about the same thing. They
        # should not be two ways of understanding it.
        understood = self._understand(toolkit, payload)
        summary = understood.subject if understood else f"{toolkit}: {trigger.replace('_', ' ').lower()}"

        journal_id = self.journal.append(
            f"accounts:{toolkit}",
            # The kind the polled path uses, so one ceiling entry covers both.
            toolkit if understood else "trigger",
            summary,
            {
                "id": event_id,
                "provider_id": event_id,
                "toolkit": toolkit,
                "trigger": trigger,
                "connection_id": connection_id,
                "external": envelope,
                **(
                    {
                        "subject": understood.subject,
                        **({"says": understood.says} if understood.says else {}),
                        **({"from": understood.entities[0]} if understood.entities else {}),
                        **({"body": understood.body[:600]} if not understood.says else {}),
                    }
                    if understood
                    else {}
                ),
            },
            trusted=False,
        )
        if journal_id is not None:
            self.memory.remember_external(
                summary,
                # The normalised body, not the raw JSON. Dumping a provider's
                # payload into long-term memory is the thing `gatekeeping`
                # exists to stop, and this path was doing it.
                (understood.body if understood else json.dumps(payload, ensure_ascii=False, default=str))[:8_000],
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

    def _already_active(self) -> set[tuple[str, str]]:
        """`(connection id, trigger slug)` for everything already enabled."""
        active: set[tuple[str, str]] = set()
        with suppress(Exception):
            page = self._sdk_triggers().list_active(limit=100)
            for row in _rows_of(page):
                item = _as_dict(row)
                connection = str(
                    item.get("connectedAccountId")
                    or item.get("connected_account_id")
                    or item.get("connectionId")
                    or ""
                )
                slug = str(item.get("triggerName") or item.get("slug") or "").upper()
                if connection and slug:
                    active.add((connection, slug))
        return active

    def _sdk_triggers(self) -> Any:
        return self.accounts._sdk().triggers

    def enable(self) -> dict[str, Any]:
        """Make sure every connected account has its trigger. Never raises.

        Idempotent by design: it reads what is already active first, and
        creating a trigger that exists is a no-op anyway. Called at startup, so
        a connection added yesterday starts delivering today without anybody
        pressing anything.
        """
        enabled: list[str] = []
        failed: list[str] = []
        try:
            connections = [row for row in self.accounts.connections() if row.get("connected")]
        except Exception as exc:
            log.warning("could not list connections to enable triggers: %s", exc)
            return {"enabled": [], "failed": [], "error": str(exc)[:200]}

        active = self._already_active()
        for row in connections:
            toolkit = str(row.get("toolkit", "")).lower()
            connection_id = str(row.get("id", ""))
            wanted = WANTED_TRIGGERS.get(toolkit)
            if not wanted or not connection_id:
                continue
            slug, config = wanted
            if (connection_id, slug) in active:
                log.info("trigger already live | %s -> %s", toolkit, slug)
                continue
            try:
                self._sdk_triggers().create(
                    slug, connected_account_id=connection_id, trigger_config=dict(config)
                )
            except Exception as exc:
                # Named, with the slug, because the usual cause is a slug this
                # table has wrong -- and "triggers did not work" is not enough
                # to find that. See `WANTED_TRIGGERS`.
                log.warning(
                    "could not enable %s for %s: %s", slug, toolkit, str(exc)[:200],
                    extra={"marvi_toolkit": toolkit, "marvi_trigger": slug},
                )
                failed.append(f"{toolkit}:{slug}")
                continue
            log.info(
                "trigger enabled | %s -> %s", toolkit, slug,
                extra={"marvi_toolkit": toolkit, "marvi_trigger": slug},
            )
            enabled.append(f"{toolkit}:{slug}")
        log.info(
            "account triggers ready | %d enabled, %d already live, %d failed",
            len(enabled), len(active), len(failed),
            extra={"marvi_enabled": len(enabled), "marvi_failed": len(failed)},
        )
        return {"enabled": enabled, "failed": failed}

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="marvi-composio-triggers", daemon=True
        )
        self._thread.start()
        log.info("Composio trigger listener started")
        # After the listener, so nothing is delivered into a stream nobody is
        # reading yet.
        threading.Thread(
            target=self.enable, name="marvi-trigger-enable", daemon=True
        ).start()
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
