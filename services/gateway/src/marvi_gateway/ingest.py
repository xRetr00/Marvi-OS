"""Native connected-account memory provider registry.

Each provider owns only fetch arguments and normalization. The engine owns the
shared guarantees: one bounded page per tick, per-connection cursor and health,
content-aware deduplication, untrusted memory storage, and failure isolation.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

from . import gatekeeping
from .accounts import CALENDAR_EVENTS, GMAIL_FETCH, ComposioAccounts
from .logs import get_logger

log = get_logger("memory")

MAX_PER_POLL = 10
MAX_SLACK_CHANNELS = 5


def _text(value: Any, limit: int = 500) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, default=str)
    return str(value or "").strip().replace("\r", "")[:limit]


def _data(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def _find_list(value: Any, names: tuple[str, ...]) -> list[dict[str, Any]]:
    """Find a provider list without depending on one Composio wrapper shape."""
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if not isinstance(value, dict):
        return []
    for name in names:
        rows = value.get(name)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    for child in value.values():
        if isinstance(child, (dict, list)):
            found = _find_list(child, names)
            if found:
                return found
    return []


def _pick(row: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        value: Any = row
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                value = None
                break
            value = value[part]
        if value not in (None, "", []):
            return value
    return None


def _cursor(payload: Any, records: list[dict[str, Any]], *record_paths: str) -> str:
    data = _data(payload)
    if isinstance(data, dict):
        for key in ("next_cursor", "nextCursor", "next_page_token", "nextPageToken"):
            if data.get(key):
                return str(data[key])
    newest = ""
    for row in records:
        value = _pick(row, *record_paths)
        if value and str(value) > newest:
            newest = str(value)
    return newest


@dataclass(frozen=True)
class MemoryItem:
    provider_id: str
    subject: str
    body: str
    entities: tuple[str, ...] = ()
    relation: str = "appears in"
    cursor: str = ""

    def fingerprint(self) -> str:
        body = f"{self.subject}\0{self.body}".encode("utf-8", errors="replace")
        return hashlib.sha256(body).hexdigest()[:32]


Fetch = Callable[[ComposioAccounts, str, str], tuple[list[dict[str, Any]], str]]
Normalize = Callable[[dict[str, Any]], MemoryItem | None]


@dataclass(frozen=True)
class MemoryProvider:
    toolkit: str
    label: str
    fetch: Fetch
    normalize: Normalize


class MemoryProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, MemoryProvider] = {}

    def register(self, provider: MemoryProvider) -> None:
        if provider.toolkit in self._providers:
            raise ValueError(f"memory provider already registered: {provider.toolkit}")
        self._providers[provider.toolkit] = provider

    def get(self, toolkit: str) -> MemoryProvider | None:
        return self._providers.get(toolkit.lower())

    def list(self) -> list[dict[str, str]]:
        return [
            {"toolkit": row.toolkit, "label": row.label}
            for row in self._providers.values()
        ]


class AccountSyncStore:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS account_sync_state (
        toolkit TEXT NOT NULL,
        connection_id TEXT NOT NULL,
        cursor TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'idle',
        last_attempt_at TEXT,
        last_success_at TEXT,
        last_error TEXT NOT NULL DEFAULT '',
        items_seen INTEGER NOT NULL DEFAULT 0,
        last_count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (toolkit, connection_id)
    );
    CREATE TABLE IF NOT EXISTS account_sync_seen (
        toolkit TEXT NOT NULL,
        connection_id TEXT NOT NULL,
        provider_id TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        seen_at TEXT NOT NULL,
        PRIMARY KEY (toolkit, connection_id, provider_id)
    );
    """

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            from .paths import accounts_db

            path = accounts_db()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(self.SCHEMA)
        self._db.commit()
        self._lock = RLock()

    def close(self) -> None:
        self._db.close()

    def state(self, toolkit: str, connection_id: str) -> dict[str, Any]:
        row = self._db.execute(
            "SELECT * FROM account_sync_state WHERE toolkit=? AND connection_id=?",
            (toolkit, connection_id),
        ).fetchone()
        if row is None:
            return {
                "toolkit": toolkit, "connection_id": connection_id, "cursor": "",
                "status": "idle", "last_attempt_at": None, "last_success_at": None,
                "last_error": "", "items_seen": 0, "last_count": 0,
            }
        return dict(row)

    def health(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self._db.execute(
                "SELECT * FROM account_sync_state ORDER BY toolkit, connection_id"
            ).fetchall()
        ]

    def changed(self, toolkit: str, connection_id: str, item: MemoryItem) -> bool:
        digest = item.fingerprint()
        row = self._db.execute(
            "SELECT fingerprint FROM account_sync_seen"
            " WHERE toolkit=? AND connection_id=? AND provider_id=?",
            (toolkit, connection_id, item.provider_id),
        ).fetchone()
        if row is not None and row["fingerprint"] == digest:
            return False
        self.mark_seen(toolkit, connection_id, item.provider_id, digest)
        return True

    def mark_seen(
        self, toolkit: str, connection_id: str, provider_id: str, fingerprint: str = ""
    ) -> None:
        """Record that a source was ingested, without requiring a `MemoryItem`.

        `changed()` is the usual caller, for a fetched-and-normalized record.
        Realtime triggers ingest one event at a time and never build a
        `MemoryItem`, but their memory write uses the same `provider_id` as
        its `source` — so recording it here, through the same call, is what
        makes a trigger-sourced memory retractable by connection at disconnect
        (see `AccountIngest.retract_connection`), the same as a polled one.
        """
        with self._lock:
            self._db.execute(
                "INSERT INTO account_sync_seen"
                " (toolkit, connection_id, provider_id, fingerprint, seen_at) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(toolkit, connection_id, provider_id) DO UPDATE SET"
                " fingerprint=excluded.fingerprint, seen_at=excluded.seen_at",
                (toolkit, connection_id, provider_id, fingerprint, datetime.now(UTC).isoformat()),
            )
            self._db.commit()

    def provider_ids(self, toolkit: str, connection_id: str) -> list[str]:
        """Every memory `source` this connection has ever written.

        This is the retraction ledger: each value here is exactly the
        `source` a memory was written with, so deleting a memory for each one
        undoes what the connection put into the graph.
        """
        rows = self._db.execute(
            "SELECT provider_id FROM account_sync_seen WHERE toolkit=? AND connection_id=?",
            (toolkit, connection_id),
        ).fetchall()
        return [str(row["provider_id"]) for row in rows]

    def count_seen(self, toolkit: str, connection_id: str = "") -> int:
        """How many items this connection (or, with no id, this toolkit) has
        ingested — the number a disconnect confirmation shows before it acts."""
        if connection_id:
            row = self._db.execute(
                "SELECT COUNT(*) AS n FROM account_sync_seen WHERE toolkit=? AND connection_id=?",
                (toolkit, connection_id),
            ).fetchone()
        else:
            row = self._db.execute(
                "SELECT COUNT(*) AS n FROM account_sync_seen WHERE toolkit=?", (toolkit,)
            ).fetchone()
        return int(row["n"])

    def clear(self, toolkit: str, connection_id: str) -> None:
        """Drop the cursor and seen-ledger for one connection, after retraction.

        So a reconnect starts over rather than resuming from a cursor whose
        memories no longer exist — resuming would silently skip everything
        already "seen" instead of re-ingesting it.
        """
        with self._lock:
            self._db.execute(
                "DELETE FROM account_sync_seen WHERE toolkit=? AND connection_id=?",
                (toolkit, connection_id),
            )
            self._db.execute(
                "DELETE FROM account_sync_state WHERE toolkit=? AND connection_id=?",
                (toolkit, connection_id),
            )
            self._db.commit()

    def finish(
        self,
        toolkit: str,
        connection_id: str,
        *,
        cursor: str,
        count: int,
        error: str = "",
    ) -> None:
        now = datetime.now(UTC).isoformat()
        previous = self.state(toolkit, connection_id)
        success = not error
        with self._lock:
            self._db.execute(
                "INSERT INTO account_sync_state"
                " (toolkit, connection_id, cursor, status, last_attempt_at, last_success_at,"
                " last_error, items_seen, last_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(toolkit, connection_id) DO UPDATE SET"
                " cursor=excluded.cursor, status=excluded.status, last_attempt_at=excluded.last_attempt_at,"
                " last_success_at=excluded.last_success_at, last_error=excluded.last_error,"
                " items_seen=excluded.items_seen, last_count=excluded.last_count",
                (
                    toolkit, connection_id, cursor or previous["cursor"],
                    "ready" if success else "error", now,
                    now if success else previous["last_success_at"], error[:300],
                    int(previous["items_seen"]) + count, count,
                ),
            )
            self._db.commit()


def _execute(
    accounts: ComposioAccounts, action: str, arguments: dict[str, Any], connection_id: str
) -> Any:
    # Tool definitions evolve. Drop optional hints the pinned live schema no
    # longer accepts instead of turning one renamed pagination field into a
    # permanently unhealthy provider.
    try:
        schema = accounts.tool(action).input_schema
        properties = schema.get("properties") if isinstance(schema, dict) else None
        if isinstance(properties, dict) and properties:
            arguments = {key: value for key, value in arguments.items() if key in properties}
    except Exception:
        # Tests, an offline schema endpoint, and older SDKs still execute the
        # known provider contract; the tool call itself remains authoritative.
        pass
    try:
        return accounts.execute(action, arguments, connected_account_id=connection_id or None)
    except TypeError as exc:
        # Test doubles and the pre-lifecycle adapter expose the old signature.
        if "connected_account_id" not in str(exc):
            raise
        return accounts.execute(action, arguments)


def _fetch_one(
    action: str,
    args: Callable[[str], dict[str, Any]],
    names: tuple[str, ...],
    cursor_paths: tuple[str, ...],
) -> Fetch:
    def fetch(accounts: ComposioAccounts, connection_id: str, cursor: str):
        payload = _execute(accounts, action, args(cursor), connection_id)
        records = _find_list(_data(payload), names)[:MAX_PER_POLL]
        return records, _cursor(payload, records, *cursor_paths) or cursor

    return fetch


def _fetch_slack(accounts: ComposioAccounts, connection_id: str, cursor: str):
    channels_payload = _execute(
        accounts,
        "SLACK_LIST_CONVERSATIONS",
        {"exclude_archived": True, "limit": MAX_SLACK_CHANNELS},
        connection_id,
    )
    channels = _find_list(_data(channels_payload), ("channels", "items"))[:MAX_SLACK_CHANNELS]
    messages: list[dict[str, Any]] = []
    for channel in channels:
        channel_id = _pick(channel, "id", "channel_id")
        if not channel_id:
            continue
        args: dict[str, Any] = {"channel": channel_id, "limit": MAX_PER_POLL}
        if cursor:
            args["oldest"] = cursor
        payload = _execute(accounts, "SLACK_FETCH_CONVERSATION_HISTORY", args, connection_id)
        for message in _find_list(_data(payload), ("messages", "items")):
            message = dict(message)
            message["_channel"] = _pick(channel, "name") or channel_id
            messages.append(message)
            if len(messages) >= MAX_PER_POLL:
                break
        if len(messages) >= MAX_PER_POLL:
            break
    return messages, _cursor({}, messages, "ts", "timestamp") or cursor


def _fetch_github(accounts: ComposioAccounts, connection_id: str, cursor: str):
    profile = _execute(accounts, "GITHUB_GET_THE_AUTHENTICATED_USER", {}, connection_id)
    login = _pick(_data(profile) if isinstance(_data(profile), dict) else {}, "login", "data.login")
    query = f"involves:{login or '@me'}"
    if cursor:
        query += f" updated:>{cursor}"
    payload = _execute(
        accounts,
        "GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS",
        {"q": query, "sort": "updated", "order": "desc", "per_page": MAX_PER_POLL, "page": 1},
        connection_id,
    )
    records = _find_list(_data(payload), ("items", "issues", "results"))[:MAX_PER_POLL]
    return records, _cursor(payload, records, "updated_at") or cursor


def _normalise_email(row: dict[str, Any]) -> MemoryItem | None:
    identifier = _pick(row, "messageId", "message_id", "id")
    if not identifier:
        return None
    sender = _text(_pick(row, "sender", "from", "from.email", "payload.headers.From"), 160)
    subject = _text(_pick(row, "subject") or "(no subject)", 160)
    body = _text(_pick(row, "messageText", "body", "snippet", "preview") or "", 3_000)
    return MemoryItem(
        f"composio:gmail:{identifier}", f"Email: {subject}",
        f"From {sender}\n\n{body}" if sender else body,
        tuple(entity for entity in (sender,) if entity),
        "sent",
        _text(_pick(row, "internalDate", "date", "timestamp"), 80),
    )


#: An ISO timestamp, as opposed to a page token.
#:
#: Every provider below decided this with `"T" in cursor` -- the T between the
#: date and the time. Google Calendar's page token is base64, and base64
#: contains the letter T about as often as any other:
#:
#:   EoABCn4SfAoGCKTJh7AGEnIKcApuXzZ0bG5hcXJsZTVwNmNwYjRkaG1qNHBocGVn...
#:                    ^
#:
#: So a page token was sent as `timeMin`, Composio answered "Unable to parse
#: time", and the calendar sync failed on every attempt from the first
#: successful page onwards. Twelve hours of it in one log, every ninety
#: seconds, with a full traceback each time.
#:
#: Anchored at the start, because a cursor either begins with a date or it is
#: not one.
_ISO_AT = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]")


def _is_timestamp(cursor: str) -> bool:
    return bool(cursor) and bool(_ISO_AT.match(cursor.strip()))


def _normalise_calendar(row: dict[str, Any]) -> MemoryItem | None:
    identifier = _pick(row, "id", "event_id")
    if not identifier:
        return None
    summary = _text(_pick(row, "summary", "title") or "(untitled event)", 160)
    when = _text(_pick(row, "start.dateTime", "start.date", "start_time"), 100)
    description = _text(_pick(row, "description", "location") or "", 1_500)
    body = "\n".join(part for part in (f"Starts {when}" if when else "", description) if part)
    return MemoryItem(
        f"composio:googlecalendar:{identifier}", f"Event: {summary}", body or summary,
        cursor=_text(_pick(row, "updated", "start.dateTime", "start.date"), 80),
    )


def _normalise_slack(row: dict[str, Any]) -> MemoryItem | None:
    identifier = _pick(row, "client_msg_id", "ts", "id")
    if not identifier:
        return None
    channel = _text(_pick(row, "_channel", "channel_name", "channel"), 100)
    user = _text(_pick(row, "user_name", "username", "user"), 120)
    text = _text(_pick(row, "text", "message") or "", 3_000)
    return MemoryItem(
        f"composio:slack:{channel}:{identifier}",
        f"Slack #{channel}: {text[:100] or '(message)'}",
        f"From {user}\n\n{text}" if user else text,
        tuple(entity for entity in (user,) if entity), "posted",
        _text(_pick(row, "ts", "timestamp"), 80),
    )


def _notion_title(row: dict[str, Any]) -> str:
    direct = _pick(row, "title", "name")
    if isinstance(direct, str):
        return direct
    properties = row.get("properties")
    if isinstance(properties, dict):
        for prop in properties.values():
            if not isinstance(prop, dict):
                continue
            rich = prop.get("title") or prop.get("rich_text")
            if isinstance(rich, list):
                text = "".join(_text(_pick(part, "plain_text", "text.content"), 300) for part in rich if isinstance(part, dict))
                if text:
                    return text
    return "Untitled"


def _normalise_notion(row: dict[str, Any]) -> MemoryItem | None:
    identifier = _pick(row, "id", "pageId", "page_id")
    if not identifier:
        return None
    title = _text(_notion_title(row), 180)
    url = _text(_pick(row, "url", "public_url"), 500)
    edited = _text(_pick(row, "last_edited_time", "lastEditedTime"), 80)
    return MemoryItem(
        f"composio:notion:{identifier}", f"Notion: {title}",
        "\n".join(part for part in (url, _text(row, 3_000)) if part), cursor=edited,
    )


def _normalise_github(row: dict[str, Any]) -> MemoryItem | None:
    identifier = _pick(row, "id", "node_id", "number")
    if not identifier:
        return None
    title = _text(_pick(row, "title") or "Untitled issue", 180)
    repo = _text(_pick(row, "repository_url", "repository.full_name", "base.repo.full_name"), 200)
    state = _text(_pick(row, "state"), 40)
    body = _text(_pick(row, "body") or "", 3_000)
    url = _text(_pick(row, "html_url", "url"), 500)
    return MemoryItem(
        f"composio:github:{identifier}", f"GitHub: {title}",
        "\n".join(part for part in (repo, state, url, body) if part),
        cursor=_text(_pick(row, "updated_at", "created_at"), 80),
    )


def _normalise_drive(row: dict[str, Any]) -> MemoryItem | None:
    identifier = _pick(row, "id", "file_id")
    if not identifier:
        return None
    name = _text(_pick(row, "name", "title") or "Untitled file", 180)
    modified = _text(_pick(row, "modifiedTime", "modified_time", "modifiedDate"), 80)
    mime = _text(_pick(row, "mimeType", "mime_type"), 120)
    link = _text(_pick(row, "webViewLink", "web_view_link", "url"), 500)
    return MemoryItem(
        f"composio:googledrive:{identifier}", f"Drive: {name}",
        "\n".join(part for part in (mime, modified, link) if part), cursor=modified,
    )


def default_registry() -> MemoryProviderRegistry:
    registry = MemoryProviderRegistry()
    registry.register(
        MemoryProvider(
            "gmail", "Gmail", _fetch_one(
                GMAIL_FETCH,
                lambda cursor: {
                    "max_results": MAX_PER_POLL, "verbose": False,
                    **({"query": f"after:{cursor}"} if cursor.isdigit() else {}),
                    **({"page_token": cursor} if cursor and not cursor.isdigit() else {}),
                },
                ("messages", "items"), ("internalDate", "date", "timestamp"),
            ), _normalise_email,
        )
    )
    registry.register(
        MemoryProvider(
            "googlecalendar", "Google Calendar", _fetch_one(
                CALENDAR_EVENTS,
                lambda cursor: {
                    "calendarId": "primary", "maxResults": MAX_PER_POLL, "singleEvents": True,
                    "orderBy": "startTime",
                    **({"timeMin": cursor} if _is_timestamp(cursor) else {}),
                    **({"pageToken": cursor} if cursor and not _is_timestamp(cursor) else {}),
                },
                ("items", "events"), ("updated", "start.dateTime", "start.date"),
            ), _normalise_calendar,
        )
    )
    registry.register(MemoryProvider("slack", "Slack", _fetch_slack, _normalise_slack))
    registry.register(
        MemoryProvider(
            "notion", "Notion", _fetch_one(
                "NOTION_FETCH_DATA",
                lambda cursor: {
                    # `fetch_type` became required upstream and the sync has
                    # failed on every attempt since -- "Following fields are
                    # missing: {'fetch_type'}" -- while the filter below said
                    # the same thing in the older shape. Both are sent: the
                    # filter is harmless where it is ignored, and removing it
                    # would break whichever deployments still want it.
                    #
                    # Plural. The singular was accepted by nothing: every poll
                    # since has failed with "Input should be 'pages',
                    # 'databases' or 'all'" -- 77 consecutive syncs in the log,
                    # each one a Notion workspace that never reached memory.
                    # The `filter` below keeps its singular "page" because that
                    # is Notion's own object-type vocabulary and a different
                    # field entirely.
                    "fetch_type": "pages",
                    "page_size": MAX_PER_POLL,
                    "filter": {"value": "page", "property": "object"},
                    "sort": {"direction": "descending", "timestamp": "last_edited_time"},
                    **({"start_cursor": cursor} if cursor and not _is_timestamp(cursor) else {}),
                },
                ("results", "items", "pages"), ("last_edited_time", "lastEditedTime"),
            ), _normalise_notion,
        )
    )
    registry.register(MemoryProvider("github", "GitHub", _fetch_github, _normalise_github))
    registry.register(
        MemoryProvider(
            "googledrive", "Google Drive", _fetch_one(
                "GOOGLEDRIVE_LIST_FILES",
                lambda cursor: {
                    "page_size": MAX_PER_POLL, "order_by": "modifiedTime desc",
                    "q": "trashed = false",
                    **({"page_token": cursor} if cursor and not _is_timestamp(cursor) else {}),
                },
                ("files", "items"), ("modifiedTime", "modified_time", "modifiedDate"),
            ), _normalise_drive,
        )
    )
    return registry


class AccountIngest:
    """Runs registered providers and records new/updated items in memory."""

    def __init__(
        self,
        accounts: ComposioAccounts,
        memory: Any,
        store: AccountSyncStore | None = None,
        registry: MemoryProviderRegistry | None = None,
        cognition: Any = None,
    ) -> None:
        self.accounts = accounts
        self.memory = memory
        self.store = store or AccountSyncStore()
        self.registry = registry or default_registry()
        #: The model that judges what an account is worth remembering. Optional
        #: because a Gateway with no auxiliary model still has to ingest; with
        #: none, `gatekeeping` keeps everything rather than nothing.
        self.cognition = cognition

    # Compatibility helpers retained as useful provider-level contracts.
    normalise_email = staticmethod(lambda row: _item_dict(_normalise_email(row)))
    normalise_calendar = staticmethod(lambda row: _item_dict(_normalise_calendar(row)))

    def health(self) -> dict[str, Any]:
        return {"providers": self.registry.list(), "connections": self.store.health()}

    def retract_preview(self, toolkit: str, connection_id: str = "") -> int:
        """How many ingested items a disconnect would retract.

        Read before `retract_connection` acts, so a disconnect confirmation
        can say how much is about to go rather than deleting silently.
        """
        return self.store.count_seen(toolkit, connection_id)

    def retract_connection(self, toolkit: str, connection_id: str) -> dict[str, Any]:
        """Undo what one connection put into the graph.

        `ComposioAccounts.delete` only ever revoked the OAuth grant and
        invalidated the connection cache — nothing touched memory, so
        disconnecting Gmail left every ingested email sitting in the graph,
        still recalled and spoken, with no live connection left to correct
        it. The seen-row ledger already keys every ingested item by
        `(toolkit, connection_id, provider_id)`, and a memory's `source` is
        exactly that `provider_id`, so retracting is a lookup and a delete
        rather than a new subsystem.
        """
        sources = self.store.provider_ids(toolkit, connection_id)
        removed = sum(self.memory.forget_by_source(source) for source in sources)
        self.store.clear(toolkit, connection_id)
        log.info(
            "account memory retracted",
            extra={
                "marvi_toolkit": toolkit,
                "marvi_connection_id": connection_id,
                "marvi_sources": len(sources),
                "marvi_removed": removed,
            },
        )
        return {
            "toolkit": toolkit,
            "connection_id": connection_id,
            "sources": len(sources),
            "removed": removed,
        }

    def sync_connection(self, toolkit: str, connection_id: str = "") -> dict[str, Any]:
        started = time.perf_counter()
        provider = self.registry.get(toolkit)
        if provider is None:
            log.warning(
                "account memory sync has no provider",
                extra={"marvi_toolkit": toolkit, "marvi_connection_id": connection_id},
            )
            return {"ingested": [], "skipped": 0, "errors": [f"{toolkit}: no memory provider"]}
        policy = self.accounts.state.policy(toolkit)
        if not policy["sync_enabled"]:
            log.info(
                "account memory sync skipped by user policy",
                extra={"marvi_toolkit": toolkit, "marvi_connection_id": connection_id},
            )
            return {"ingested": [], "skipped": 0, "errors": [], "disabled": True}
        state = self.store.state(toolkit, connection_id)
        log.info(
            "account memory sync started",
            extra={
                "marvi_toolkit": toolkit,
                "marvi_connection_id": connection_id,
                "marvi_has_cursor": bool(state["cursor"]),
            },
        )
        try:
            records, next_cursor = provider.fetch(self.accounts, connection_id, state["cursor"])
        except Exception as exc:
            error = f"{toolkit}: {str(exc)[:220]}"
            self.store.finish(
                toolkit, connection_id, cursor=state["cursor"], count=0, error=error
            )
            log.warning(
                "account memory sync failed",
                extra={
                    "marvi_toolkit": toolkit,
                    "marvi_connection_id": connection_id,
                    "marvi_latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "marvi_error": str(exc)[:240],
                },
                exc_info=True,
            )
            return {"ingested": [], "skipped": 0, "errors": [error]}

        ingested: list[str] = []
        events: list[dict[str, str]] = []
        skipped = 0
        # Judged together, before anything is written. This replaced a regex
        # over sender addresses that scored 8 of 11 on real mail and lost three
        # things worth keeping -- an exam result, a dentist appointment and a
        # rent bill, all from `noreply` senders, all dropped for the shape of
        # the envelope rather than what was inside. The model scored 11 of 11
        # on the same set and kept no junk. It fails open: see `gatekeeping`.
        candidates = []
        for record in records[:MAX_PER_POLL]:
            item = provider.normalize(record)
            if item is None or not self.store.changed(toolkit, connection_id, item):
                skipped += 1
                continue
            candidates.append(item)
        before = len(candidates)
        candidates = gatekeeping.worth_keeping(self.cognition, candidates)
        skipped += before - len(candidates)
        for item in candidates:
            self.memory.remember_external(item.subject, item.body, source=item.provider_id)
            for entity in item.entities:
                self.memory.link(
                    entity, item.relation, item.subject, source=item.provider_id, trusted=False
                )
            ingested.append(item.subject)
            events.append(
                {
                    "id": item.provider_id,
                    "provider_id": item.provider_id,
                    "toolkit": toolkit,
                    "subject": item.subject,
                }
            )
        self.store.finish(toolkit, connection_id, cursor=next_cursor, count=len(ingested))
        log.info(
            "account memory sync completed",
            extra={
                "marvi_toolkit": toolkit,
                "marvi_connection_id": connection_id,
                "marvi_fetched": len(records),
                "marvi_ingested": len(ingested),
                "marvi_skipped": skipped,
                "marvi_has_next_cursor": bool(next_cursor),
                "marvi_latency_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return {"ingested": ingested, "events": events, "skipped": skipped, "errors": []}

    def poll(self) -> dict[str, Any]:
        started = time.perf_counter()
        ingested: list[str] = []
        events: list[dict[str, str]] = []
        skipped = 0
        errors: list[str] = []
        try:
            rows = self.accounts.connection_rows()
        except Exception:
            # Older adapters/test doubles intentionally expose only summary rows.
            try:
                rows = self.accounts.connections()
            except Exception as exc:
                return {"ingested": [], "skipped": 0, "errors": [str(exc)[:220]]}

        for row in rows:
            if not row.get("connected") or self.registry.get(str(row.get("toolkit", ""))) is None:
                continue
            result = self.sync_connection(str(row["toolkit"]), str(row.get("id", "")))
            ingested.extend(result.get("ingested", []))
            events.extend(result.get("events", []))
            skipped += int(result.get("skipped", 0))
            errors.extend(result.get("errors", []))
        result = {
            "at": datetime.now(UTC).isoformat(), "ingested": ingested,
            "events": events, "skipped": skipped, "errors": errors,
        }
        log.info(
            "account memory poll completed",
            extra={
                "marvi_connections": len(rows),
                "marvi_ingested": len(ingested),
                "marvi_skipped": skipped,
                "marvi_errors": len(errors),
                "marvi_latency_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return result


def _item_dict(item: MemoryItem | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        "provider_id": item.provider_id,
        "subject": item.subject,
        "body": item.body,
        "entities": list(item.entities),
    }
