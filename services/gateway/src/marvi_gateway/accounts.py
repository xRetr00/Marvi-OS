"""Composio account lifecycle and scoped agent capability broker.

Composio owns provider credentials and hosted authorization. Marvi owns the
user-facing lifecycle, each toolkit's capability ceiling, confirmation, audit,
and the untrusted-content boundary. A model never receives a project API key,
OAuth token, or unrestricted Composio session.
"""

from __future__ import annotations

import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from .untrusted import wrap_external

CONNECTIONS_CACHE_SECONDS = 30.0
TOOLS_CACHE_SECONDS = 10 * 60.0
DEAD_STATUSES = {"expired", "revoked", "failed", "disabled", "inactive"}
LIVE_STATUSES = {"active", "connected", "success"}
ACCOUNT_SCOPES = ("read", "write", "admin")
SCOPE_RANK = {name: index for index, name in enumerate(ACCOUNT_SCOPES)}

GMAIL_FETCH = "GMAIL_FETCH_EMAILS"
GMAIL_SEND = "GMAIL_SEND_EMAIL"
CALENDAR_EVENTS = "GOOGLECALENDAR_EVENTS_LIST"

#: Toolkits Marvi ships first-class support for: a native memory provider
#: (`ingest.py`), and — for most of them — a curated action-effect catalog
#: below. Shown as "preview" cards in Connectors before the user connects
#: them. A toolkit outside this tuple can still be connected and used through
#: the generic `account_tool_search`/`account_tool_execute` broker; it is
#: just not advertised until connected, and its actions fall back to the word
#: heuristic in `classify_action`.
NATIVE_MEMORY_TOOLKITS = (
    "gmail", "googlecalendar", "slack", "notion", "github", "googledrive",
)

TOOLKIT_LABELS = {
    "gmail": "Gmail",
    "googlecalendar": "Google Calendar",
    "slack": "Slack",
    "notion": "Notion",
    "github": "GitHub",
    "googledrive": "Google Drive",
}

#: The reviewed effect overlay: toolkit -> {slug: effect}, for the toolkits
#: Marvi actually uses. A toolkit that appears here is one Marvi's own team
#: has checked action by action; see `classify_action` for why an uncurated
#: slug on a toolkit that IS in this dict is refused rather than guessed. Not
#: exhaustive — it grows as more actions are reviewed against the live
#: catalog (RFC-NATIVE-CONNECTORS Gate 4), not as a one-time exercise.
ACTION_CATALOG: dict[str, dict[str, Literal["read", "write", "admin"]]] = {
    "gmail": {
        "GMAIL_FETCH_EMAILS": "read",
        "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID": "read",
        "GMAIL_FETCH_MESSAGE_BY_THREAD_ID": "read",
        "GMAIL_LIST_THREADS": "read",
        "GMAIL_LIST_LABELS": "read",
        "GMAIL_SEND_EMAIL": "write",
        "GMAIL_CREATE_EMAIL_DRAFT": "write",
        "GMAIL_REPLY_TO_THREAD": "write",
        "GMAIL_MOVE_TO_TRASH": "admin",
        "GMAIL_DELETE_MESSAGE": "admin",
    },
    "googlecalendar": {
        "GOOGLECALENDAR_EVENTS_LIST": "read",
        "GOOGLECALENDAR_FIND_EVENT": "read",
        "GOOGLECALENDAR_CREATE_EVENT": "write",
        "GOOGLECALENDAR_UPDATE_EVENT": "write",
        "GOOGLECALENDAR_QUICK_ADD": "write",
        "GOOGLECALENDAR_DELETE_EVENT": "admin",
    },
    "github": {
        "GITHUB_GET_THE_AUTHENTICATED_USER": "read",
        "GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS": "read",
        "GITHUB_LIST_REPOSITORIES": "read",
        "GITHUB_GET_A_REPOSITORY": "read",
        "GITHUB_CREATE_AN_ISSUE": "write",
        "GITHUB_CREATE_A_PULL_REQUEST": "write",
        "GITHUB_ADD_A_COMMENT_TO_AN_ISSUE": "write",
        "GITHUB_MERGE_A_PULL_REQUEST": "admin",
        "GITHUB_DELETE_A_REPOSITORY": "admin",
    },
    "notion": {
        "NOTION_FETCH_DATA": "read",
        "NOTION_CREATE_PAGE": "write",
        "NOTION_UPDATE_PAGE": "write",
        "NOTION_APPEND_BLOCK_CHILDREN": "write",
        "NOTION_DELETE_BLOCK": "admin",
    },
    "slack": {
        "SLACK_LIST_CONVERSATIONS": "read",
        "SLACK_FETCH_CONVERSATION_HISTORY": "read",
        "SLACK_LIST_ALL_USERS": "read",
        "SLACK_SEND_MESSAGE": "write",
        "SLACK_UPDATE_A_SLACK_MESSAGE": "write",
        "SLACK_DELETE_A_SLACK_MESSAGE": "admin",
    },
}

_ADMIN_WORDS = {
    "DELETE", "TRASH", "REMOVE", "REVOKE", "DISABLE", "ENABLE", "DESTROY",
    "ARCHIVE", "UNARCHIVE", "PERMISSION", "MEMBER", "INVITE", "SHARE",
}
_WRITE_WORDS = {
    "SEND", "CREATE", "UPDATE", "REPLY", "FORWARD", "APPEND", "INSERT",
    "ADD", "POST", "PATCH", "WRITE", "UPLOAD", "MOVE", "COPY", "DRAFT",
    "STAR", "MERGE", "CLOSE", "OPEN", "MARK", "MODIFY", "SET",
}
_READ_WORDS = {
    "GET", "LIST", "FETCH", "SEARCH", "FIND", "RETRIEVE", "READ", "VIEW",
    "QUERY", "LOOKUP", "CHECK", "COUNT", "TEST", "DESCRIBE", "DOWNLOAD",
    "EXPORT", "ENUM", "HISTORY", "STATUS", "DETAILS", "INFO",
}


class AccountsUnavailableError(Exception):
    """The SDK or project key is unavailable."""


class AccountAuthError(Exception):
    """A project key or connected-account authorization was rejected."""


class AccountScopeError(Exception):
    """The user-selected toolkit scope refuses a remote action."""


class AccountRateLimitedError(Exception):
    pass


class AccountTransientError(Exception):
    pass


def api_key() -> str | None:
    return (os.environ.get("COMPOSIO_API_KEY") or "").strip() or None


def default_user_id() -> str:
    """A stable identity for this Marvi installation, generated once.

    Composio's own docs warn against `"default"` in production because
    connections are stored under this identifier — reusing the literal across
    installations means they address the same Composio identity. openhuman
    threads an equivalent `entity_id` through every authorize/execute call;
    `COMPOSIO_ENTITY_ID` is Marvi's version for anyone who wants to pin one
    explicitly. Absent that, an id is generated the first time it is needed
    and persisted beside the rest of Marvi's local state, so every
    installation gets its own address without asking anyone to configure
    anything.
    """
    override = (os.environ.get("COMPOSIO_ENTITY_ID") or "").strip()
    if override:
        return override
    from .paths import composio_entity_file

    path = composio_entity_file()
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except OSError:
        existing = ""
    if existing:
        return existing
    generated = f"marvi-{uuid.uuid4().hex}"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(generated + "\n", encoding="utf-8")
    except OSError:
        # A locked or unwritable path is not worth failing startup over — the
        # generated id still works for this process, it just will not
        # survive a restart.
        pass
    return generated


def _status_of(exc: Exception) -> int | None:
    return getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )


def _reraise(exc: Exception) -> None:
    if isinstance(
        exc,
        (
            AccountsUnavailableError,
            AccountAuthError,
            AccountScopeError,
            AccountRateLimitedError,
            AccountTransientError,
        ),
    ):
        raise exc
    status = _status_of(exc)
    if status == 429:
        raise AccountRateLimitedError("Composio rate limit reached.") from exc
    if status in (401, 403):
        raise AccountAuthError(f"Composio rejected the request ({status}).") from exc
    if isinstance(status, int) and status >= 500:
        raise AccountTransientError(f"Composio server error ({status}).") from exc
    raise AccountTransientError(str(exc)) from exc


def _as_dict(result: Any) -> Any:
    for attr in ("model_dump", "dict", "to_dict"):
        method = getattr(result, attr, None)
        if callable(method):
            try:
                return method()
            except Exception:
                continue
    if isinstance(result, (dict, list, str, int, float, bool, type(None))):
        return result
    return str(result)


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _toolkit_slug(item: Any) -> str:
    toolkit = _get(item, "toolkit", {})
    return str(_get(toolkit, "slug", "") or _get(item, "toolkit_slug", "")).lower()


def toolkit_from_action(action: str) -> str:
    upper = action.strip().upper()
    for prefix, toolkit in (
        ("GOOGLECALENDAR_", "googlecalendar"),
        ("GOOGLEDRIVE_", "googledrive"),
        ("MICROSOFT_TEAMS_", "microsoft_teams"),
        ("ONE_DRIVE_", "one_drive"),
        ("ZOHO_MAIL_", "zoho_mail"),
    ):
        if upper.startswith(prefix):
            return toolkit
    return upper.partition("_")[0].lower()


def classify_action(action: str, toolkit: str | None = None) -> Literal["read", "write", "admin"]:
    """Classify a remote action's effect.

    A toolkit with a curated catalog above is authoritative for every slug in
    it, and refuses — rather than guesses — for one that is not. openhuman's
    review (PR #4702) found that the word heuristic below calls an uncurated
    *write* action "read" whenever its slug happens to contain GET, LIST,
    CHECK or STATUS, because Composio names actions for what they retrieve,
    not always for everything else they do. A toolkit with no catalog has
    nothing more authoritative to check a slug against yet, so it keeps the
    heuristic, which already fails closed on a genuinely unfamiliar verb.
    """
    slug = action.strip().upper()
    resolved_toolkit = (toolkit or toolkit_from_action(slug)).strip().lower()
    catalog = ACTION_CATALOG.get(resolved_toolkit)
    if catalog is not None:
        # Not `.get(slug, "admin")` by accident: an action this toolkit's
        # catalog does not mention is exactly the case the word heuristic
        # gets wrong, so it is refused the same way an unfamiliar verb is
        # below, never handed to that heuristic as a fallback.
        return catalog.get(slug, "admin")

    words = set(slug.split("_"))
    if words & _ADMIN_WORDS:
        return "admin"
    if words & _WRITE_WORDS:
        return "write"
    if words & _READ_WORDS:
        return "read"
    # Composio can add actions between Marvi releases. An unfamiliar verb is
    # never granted confirmation-free access merely because we have not seen
    # it before.
    return "admin"


class AccountStateStore:
    """Durable Marvi policy. No provider credentials are stored here."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS account_policy (
        toolkit TEXT PRIMARY KEY,
        scope TEXT NOT NULL DEFAULT 'read',
        sync_enabled INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL
    );
    """

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            from .paths import accounts_db

            path = accounts_db()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(self.SCHEMA)
        self._db.commit()
        self._lock = RLock()

    def close(self) -> None:
        self._db.close()

    def policy(self, toolkit: str) -> dict[str, Any]:
        slug = toolkit.strip().lower()
        row = self._db.execute(
            "SELECT scope, sync_enabled, updated_at FROM account_policy WHERE toolkit = ?",
            (slug,),
        ).fetchone()
        if row is None:
            return {"scope": "read", "sync_enabled": True, "updated_at": None}
        return {
            "scope": row["scope"],
            "sync_enabled": bool(row["sync_enabled"]),
            "updated_at": row["updated_at"],
        }

    def update(
        self, toolkit: str, *, scope: str | None = None, sync_enabled: bool | None = None
    ) -> dict[str, Any]:
        slug = toolkit.strip().lower()
        if not slug:
            raise ValueError("toolkit is required")
        current = self.policy(slug)
        selected = str(scope or current["scope"]).lower()
        if selected not in ACCOUNT_SCOPES:
            raise ValueError("scope must be read, write, or admin")
        enabled = current["sync_enabled"] if sync_enabled is None else bool(sync_enabled)
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._db.execute(
                "INSERT INTO account_policy (toolkit, scope, sync_enabled, updated_at)"
                " VALUES (?, ?, ?, ?) ON CONFLICT(toolkit) DO UPDATE SET"
                " scope=excluded.scope, sync_enabled=excluded.sync_enabled, updated_at=excluded.updated_at",
                (slug, selected, 1 if enabled else 0, now),
            )
            self._db.commit()
        return {"scope": selected, "sync_enabled": enabled, "updated_at": now}


@dataclass(frozen=True)
class DiscoveredTool:
    slug: str
    name: str
    description: str
    toolkit: str
    access: Literal["read", "write", "admin"]
    input_schema: dict[str, Any]
    version: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "toolkit": self.toolkit,
            "access": self.access,
            "input_schema": self.input_schema,
            "version": self.version,
        }


class ComposioAccounts:
    def __init__(
        self,
        key: str | None = None,
        client: Any = None,
        user_id: str | None = None,
        state: AccountStateStore | None = None,
    ) -> None:
        self._key = key if key is not None else api_key()
        self._client = client
        # `None` rather than a literal default: resolving lazily here, instead
        # of at import time, means a test or a caller with its own identity
        # scheme is never surprised by a file this module decided to write.
        self.user_id = user_id if user_id is not None else default_user_id()
        self.state = state or AccountStateStore()
        self._cached: tuple[float, list[dict[str, Any]]] | None = None
        self._tool_cache: dict[str, tuple[float, list[DiscoveredTool]]] = {}

    def available(self) -> bool:
        return bool(self._client or self._key)

    def configure(self, key: str) -> None:
        """Validate and install a project key without retaining an earlier client."""
        value = key.strip()
        if not value:
            raise ValueError("Composio API key is required")
        try:
            import composio
        except ImportError as exc:
            raise AccountsUnavailableError("The Composio SDK is not installed.") from exc
        client = composio.Composio(api_key=value)
        try:
            client.toolkits.list(limit=1, sort_by="usage")
        except Exception as exc:
            _reraise(exc)
            raise
        self._key = value
        self._client = client
        self.invalidate()

    def _sdk(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._key:
            raise AccountsUnavailableError(
                "No Composio API key. Configure COMPOSIO_API_KEY in Providers."
            )
        try:
            import composio
        except ImportError as exc:
            raise AccountsUnavailableError("The Composio SDK is not installed.") from exc
        self._client = composio.Composio(api_key=self._key)
        return self._client

    # -- catalog and OAuth lifecycle --------------------------------------

    def toolkits(self, limit: int = 100) -> list[dict[str, Any]]:
        client = self._sdk()
        try:
            result = client.toolkits.list(limit=max(1, min(limit, 100)), sort_by="usage")
        except Exception as exc:
            _reraise(exc)
            raise
        rows = []
        for item in list(_get(result, "items", []) or []):
            slug = str(_get(item, "slug", "")).lower()
            if not slug:
                continue
            rows.append(
                {
                    "slug": slug,
                    "name": str(_get(item, "name", slug)),
                    "description": str(_get(item, "description", ""))[:240],
                    "logo": str(_get(item, "logo", "") or ""),
                    "native_memory": slug in NATIVE_MEMORY_TOOLKITS,
                }
            )
        return rows

    def authorize(self, toolkit: str) -> dict[str, Any]:
        slug = toolkit.strip().lower()
        if not slug:
            raise ValueError("toolkit is required")
        try:
            result = self._sdk().toolkits.authorize(user_id=self.user_id, toolkit=slug)
        except Exception as exc:
            _reraise(exc)
            raise
        self.invalidate()
        body = _as_dict(result)
        return {
            "toolkit": slug,
            "id": str(_get(body, "id", "") or _get(body, "connected_account_id", "")),
            "redirect_url": str(_get(body, "redirect_url", "")),
            "expires_at": _get(body, "expires_at"),
        }

    def delete(self, connection_id: str) -> dict[str, Any]:
        try:
            result = self._sdk().connected_accounts.delete(connection_id, revoke_on_delete=True)
        except TypeError:
            result = self._sdk().connected_accounts.delete(connection_id)
        except Exception as exc:
            _reraise(exc)
            raise
        self.invalidate()
        return {"connection_id": connection_id, "deleted": True, "result": _as_dict(result)}

    def set_enabled(self, connection_id: str, enabled: bool) -> dict[str, Any]:
        try:
            manager = self._sdk().connected_accounts
            result = (manager.enable if enabled else manager.disable)(connection_id)
        except Exception as exc:
            _reraise(exc)
            raise
        self.invalidate()
        return {"connection_id": connection_id, "enabled": enabled, "result": _as_dict(result)}

    def refresh(self, connection_id: str) -> dict[str, Any]:
        try:
            result = self._sdk().connected_accounts.refresh(connection_id)
        except Exception as exc:
            _reraise(exc)
            raise
        self.invalidate()
        body = _as_dict(result)
        return {
            "connection_id": connection_id,
            "redirect_url": str(_get(body, "redirect_url", "")),
            "result": body,
        }

    # -- connections -------------------------------------------------------

    def connection_rows(self) -> list[dict[str, Any]]:
        try:
            result = self._sdk().connected_accounts.list(user_ids=[self.user_id], limit=100)
        except Exception as exc:
            _reraise(exc)
            raise
        rows = []
        for item in list(_get(result, "items", []) or []):
            slug = _toolkit_slug(item)
            if not slug:
                continue
            status = str(_get(item, "status", "unknown"))
            policy = self.state.policy(slug)
            rows.append(
                {
                    "id": str(_get(item, "id", "") or _get(item, "nanoid", "")),
                    "toolkit": slug,
                    "status": status,
                    "connected": status.lower() in LIVE_STATUSES,
                    "needs_reconnect": status.lower() in DEAD_STATUSES,
                    "alias": str(_get(item, "alias", "") or ""),
                    "scope": policy["scope"],
                    "sync_enabled": policy["sync_enabled"],
                }
            )
        return sorted(rows, key=lambda row: (row["toolkit"], not row["connected"], row["id"]))

    def connections(self) -> list[dict[str, Any]]:
        """Compatibility summary: one row per toolkit, preferring active."""
        best: dict[str, dict[str, Any]] = {}
        for row in self.connection_rows():
            slug = row["toolkit"]
            if slug not in best or (row["connected"] and not best[slug]["connected"]):
                best[slug] = row
        return sorted(best.values(), key=lambda row: row["toolkit"])

    def cached_connections(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._cached is None or now - self._cached[0] >= CONNECTIONS_CACHE_SECONDS:
            self._cached = (now, self.connection_rows())
        return self._cached[1]

    def invalidate(self) -> None:
        self._cached = None
        self._tool_cache.clear()

    def require_connected(self, toolkit: str) -> dict[str, Any]:
        for row in self.connection_rows():
            if row["toolkit"] == toolkit:
                if row["connected"]:
                    return row
                raise AccountAuthError(
                    f"The {toolkit} connection is {row['status'].lower()}. Reconnect it in Accounts."
                )
        raise AccountAuthError(f"No {toolkit} account is connected.")

    # -- dynamic discovery and scoped execution ---------------------------

    @staticmethod
    def _discovered(raw: Any) -> DiscoveredTool | None:
        slug = str(_get(raw, "slug", ""))
        if not slug:
            return None
        toolkit = _toolkit_slug(raw) or toolkit_from_action(slug)
        schema = _get(raw, "input_parameters", {})
        return DiscoveredTool(
            slug=slug,
            name=str(_get(raw, "name", slug)),
            description=str(_get(raw, "human_description", "") or _get(raw, "description", ""))[:500],
            toolkit=toolkit,
            access=classify_action(slug, toolkit),
            input_schema=schema if isinstance(schema, dict) else {},
            version=str(_get(raw, "version", "latest")),
        )

    def discover_tools(
        self, *, toolkit: str | None = None, query: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        connected = {row["toolkit"] for row in self.connection_rows() if row["connected"]}
        selected = toolkit.strip().lower() if toolkit else ""
        if selected and selected not in connected:
            raise AccountAuthError(f"No {selected} account is connected.")
        cache_key = f"{selected}|{(query or '').strip().lower()}|{limit}"
        cached = self._tool_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < TOOLS_CACHE_SECONDS:
            tools = cached[1]
        else:
            try:
                raw = self._sdk().tools.get_raw_composio_tools(
                    toolkits=[selected] if selected else sorted(connected),
                    search=(query or "").strip() or None,
                    limit=max(1, min(limit, 50)),
                )
            except Exception as exc:
                _reraise(exc)
                raise
            tools = [tool for item in list(raw or []) if (tool := self._discovered(item))]
            self._tool_cache[cache_key] = (time.monotonic(), tools)
        return [tool.as_dict() for tool in tools if self.scope_allows(tool.toolkit, tool.access)]

    def tool(self, action: str) -> DiscoveredTool:
        key = f"tool:{action.upper()}"
        cached = self._tool_cache.get(key)
        if cached:
            return cached[1][0]
        try:
            raw = self._sdk().tools.get_raw_composio_tool_by_slug(action.upper())
        except Exception as exc:
            _reraise(exc)
            raise
        tool = self._discovered(raw)
        if tool is None:
            raise AccountTransientError(f"Composio returned no schema for {action}")
        self._tool_cache[key] = (time.monotonic(), [tool])
        return tool

    def scope_allows(self, toolkit: str, access: str) -> bool:
        ceiling = self.state.policy(toolkit)["scope"]
        return SCOPE_RANK.get(access, 2) <= SCOPE_RANK.get(ceiling, 0)

    def tool_access(self, action: str) -> Literal["read", "write", "admin"]:
        try:
            return self.tool(action).access
        except Exception:
            # A schema/network failure cannot downgrade an action into a
            # confirmation-free read.
            return "admin"

    def execute(
        self,
        action: str,
        arguments: dict[str, Any] | None = None,
        *,
        connected_account_id: str | None = None,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "slug": action,
            "arguments": arguments or {},
            "user_id": self.user_id,
            "dangerously_skip_version_check": True,
        }
        if connected_account_id:
            kwargs["connected_account_id"] = connected_account_id
        try:
            result = self._sdk().tools.execute(**kwargs)
        except TypeError as exc:
            if "dangerously_skip_version_check" not in str(exc):
                _reraise(exc)
            kwargs.pop("dangerously_skip_version_check", None)
            result = self._sdk().tools.execute(**kwargs)
        except Exception as exc:
            _reraise(exc)
            raise
        payload = _as_dict(result)
        if isinstance(payload, dict) and payload.get("successful") is False:
            raise AccountTransientError(str(payload.get("error") or f"{action} failed"))
        return payload

    def execute_scoped(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = self.tool(action)
        self.require_connected(tool.toolkit)
        if not self.scope_allows(tool.toolkit, tool.access):
            ceiling = self.state.policy(tool.toolkit)["scope"]
            raise AccountScopeError(
                f"{tool.slug} needs {tool.access} access; {tool.toolkit} is limited to {ceiling}."
            )
        result = self.execute(tool.slug, arguments)
        if tool.access == "read":
            return wrap_external(f"composio:{tool.toolkit}:{tool.slug}", result).model_dump()
        return {"tool": tool.slug, "toolkit": tool.toolkit, "result": result}


def register_account_tools(registry: Any, accounts: ComposioAccounts) -> None:
    """Stable broker tools keep a thousand-app catalog out of every prompt."""
    from .tools import ToolSpec

    def accounts_status() -> dict[str, Any]:
        rows = accounts.connections()
        return {
            "connected": [r["toolkit"] for r in rows if r["connected"]],
            "needs_reconnect": [r["toolkit"] for r in rows if r["needs_reconnect"]],
            "accounts": rows,
        }

    def account_tool_search(query: str, toolkit: str = "", limit: int = 12) -> dict[str, Any]:
        return {
            "tools": accounts.discover_tools(
                toolkit=toolkit or None, query=query, limit=max(1, min(limit, 25))
            )
        }

    def account_tool_execute(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return accounts.execute_scoped(tool, arguments)

    def email_recent(limit: int = 5) -> dict[str, Any]:
        accounts.require_connected("gmail")
        payload = accounts.execute(
            GMAIL_FETCH, {"max_results": max(1, min(limit, 25)), "verbose": False}
        )
        return wrap_external("composio:gmail", payload).model_dump()

    def calendar_events(limit: int = 10) -> dict[str, Any]:
        accounts.require_connected("googlecalendar")
        payload = accounts.execute(
            CALENDAR_EVENTS,
            {"calendarId": "primary", "maxResults": max(1, min(limit, 25)), "singleEvents": True},
        )
        return wrap_external("composio:googlecalendar", payload).model_dump()

    def send_email(recipient_email: str, subject: str, body: str) -> Any:
        accounts.require_connected("gmail")
        if not accounts.scope_allows("gmail", "write"):
            raise AccountScopeError("Sending email needs write access; Gmail is limited to read.")
        return accounts.execute(
            GMAIL_SEND,
            {"recipient_email": recipient_email, "subject": subject, "body": body},
        )

    registry.register(ToolSpec("accounts_status", "Read connected account status", {}, False, accounts_status))
    registry.register(
        ToolSpec(
            name="account_tool_search",
            description="Discover allowed tools from connected accounts before using one",
            arguments={"query": str},
            optional={"toolkit": str, "limit": int},
            sensitive=False,
            handler=account_tool_search,
            describes={
                "query": "Capability to find, such as 'search Slack messages'",
                "toolkit": "Optional connected toolkit slug such as slack or github",
                "limit": "Maximum tool schemas to return",
            },
        )
    )
    registry.register(
        ToolSpec(
            name="account_tool_execute",
            description="Execute a discovered account tool within the user's capability ceiling",
            arguments={"tool": str, "arguments": dict},
            sensitive=False,
            external=False,
            handler=account_tool_execute,
            schema={
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "description": "Exact discovered Composio tool slug"},
                    "arguments": {
                        "type": "object",
                        "description": "Arguments matching the discovered input_schema",
                        "additionalProperties": True,
                    },
                },
                "required": ["tool", "arguments"],
                "additionalProperties": False,
            },
            sensitive_when=lambda args: accounts.tool_access(str(args.get("tool", ""))) != "read",
            external_when=lambda args: accounts.tool_access(str(args.get("tool", ""))) != "read",
        )
    )
    registry.register(
        ToolSpec("email_recent", "Read recent email", {}, False, email_recent, optional={"limit": int})
    )
    registry.register(
        ToolSpec(
            "calendar_events", "Read upcoming calendar events", {}, False, calendar_events,
            optional={"limit": int},
        )
    )
    registry.register(
        ToolSpec(
            name="send_email",
            description="Send an email",
            arguments={"recipient_email": str, "subject": str, "body": str},
            sensitive=True,
            external=True,
            handler=send_email,
        )
    )
