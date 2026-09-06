"""A pushed email is understood the same way a polled one is.

The push path had its own summary, its own memory body and its own journal
`kind`, so the policy looked up `accounts:gmail:trigger`, found nothing, and
fell through to the default. The same email was spoken when it arrived by poll
and filed silently as `activity` when it arrived by push:

    06:35  gmail: gmail new gmail message   activity  ceiling activity
    05:43  Email: 3 Mailboxes Deleted       speak     Your three Neudocs mailboxes...
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from marvi_gateway.account_triggers import AccountTriggerIngest
from marvi_gateway.ingest import default_registry
from marvi_gateway.policy import SURFACES, InitiativeSettings, WorldState, evaluate

#: A Gmail push payload, shaped the way Composio normalises a message.
PUSHED = {
    "messageId": "1a0747285c99ea93",
    "subject": "3 Mailboxes Deleted",
    "sender": "Order Notification <no-reply@icemail.ai>",
    "messageText": "Three mailboxes were deleted from your workspace.",
    "messageTimestamp": "2026-09-06T06:35:00Z",
}


class _Journal:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, dict]] = []

    def append(self, source, kind, summary, payload, trusted=False):
        self.rows.append((source, kind, summary, payload))
        return len(self.rows)


class _Memory:
    def __init__(self) -> None:
        self.written: list[tuple[str, str]] = []

    def remember_external(self, subject, body, source=""):
        self.written.append((subject, body))


class _Sync:
    """Only what `ingest` reaches for. `cognition = None` means the gatekeeper
    is skipped, so these tests exercise the filing, not the model."""

    registry = default_registry()
    cognition = None
    speaking_to = "Shereef"

    class store:  # noqa: N801
        @staticmethod
        def mark_seen(*_args, **_kwargs):
            return None

    @staticmethod
    def sync_connection(*_args, **_kwargs):
        return {"ingested": []}


@pytest.fixture
def pushed() -> tuple[_Journal, _Memory]:
    journal, memory = _Journal(), _Memory()
    ingest = AccountTriggerIngest.__new__(AccountTriggerIngest)
    ingest.accounts = type("A", (), {"user_id": ""})()
    ingest.journal = journal
    ingest.memory = memory
    ingest.sync = _Sync()
    ingest.received = 0
    ingest.last_event_at = None
    ingest.last_error = ""
    ingest.ingest(
        {
            "toolkit_slug": "gmail",
            "trigger_slug": "GMAIL_NEW_GMAIL_MESSAGE",
            "id": "evt-1",
            "payload": PUSHED,
        }
    )
    return journal, memory


def test_a_pushed_email_is_filed_like_a_polled_one(pushed) -> None:
    journal, _memory = pushed
    source, kind, summary, _payload = journal.rows[0]
    assert (source, kind) == ("accounts:gmail", "gmail"), "the policy cannot find this key"
    assert summary == "Email: 3 Mailboxes Deleted", f"filed as {summary!r}"


def test_it_can_reach_the_speaking_surface(pushed) -> None:
    journal, _memory = pushed
    source, kind, summary, payload = journal.rows[0]
    event = {
        "source": source, "kind": kind, "summary": summary, "trusted": False,
        # As if the gatekeeper had read it -- the ceiling is what is under test.
        "payload": {**payload, "says": "Three mailboxes were deleted."},
        "at": 0.0,
    }
    verdict = evaluate(
        event,
        WorldState(now=datetime(2026, 9, 6, 12, 0, tzinfo=UTC), present=True),
        InitiativeSettings(),
        wanted="speak",
    )
    assert verdict.surface == "speak", f"a pushed email stopped at {verdict.surface}"
    assert SURFACES.index(verdict.surface) >= SURFACES.index("speak")


def test_memory_gets_the_body_not_the_raw_json(pushed) -> None:
    # Dumping a provider's payload into long-term memory is the thing
    # `gatekeeping` exists to stop, and this path was doing it.
    _journal, memory = pushed
    subject, body = memory.written[0]
    assert subject == "Email: 3 Mailboxes Deleted"
    assert "messageId" not in body, "wrote the raw JSON into memory"
    assert "Three mailboxes were deleted" in body


def test_an_unreadable_payload_still_reaches_the_journal() -> None:
    """Falling back rather than dropping: an event nobody can parse is still
    an event, and losing it silently is the worse failure."""
    journal, memory = _Journal(), _Memory()
    ingest = AccountTriggerIngest.__new__(AccountTriggerIngest)
    ingest.accounts = type("A", (), {"user_id": ""})()
    ingest.journal, ingest.memory, ingest.sync = journal, memory, _Sync()
    ingest.received = 0
    ingest.last_event_at = None
    ingest.last_error = ""

    ingest.ingest({"toolkit_slug": "gmail", "trigger_slug": "X", "id": "e2", "payload": {"odd": 1}})

    source, kind, summary, _payload = journal.rows[0]
    assert (source, kind) == ("accounts:gmail", "trigger")
    assert summary.startswith("gmail:")
