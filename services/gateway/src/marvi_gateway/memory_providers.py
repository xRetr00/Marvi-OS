"""One selected durable-memory provider behind Marvi's existing seam.

The protocol is intentionally smaller than :class:`MemoryStore`. Retrieval
and extraction belong to the selected provider; embeddings never cross this
boundary. ``MemoryRuntime`` preserves the older Gateway and ARC call sites
while routing durable facts through exactly one provider at a time.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

import httpx

from .logs import get_logger
from .memory import MemoryStore
from .untrusted import wrap_external

log = get_logger("memory")

PROVIDER_SETTING = "MARVI_MEMORY_PROVIDER"
URL_SETTING = "MARVI_MEMORY_URL"
KEY_SETTING = "MARVI_MEMORY_KEY"
USER_SETTING = "MARVI_MEMORY_USER_ID"
WORKSPACE_SETTING = "MARVI_MEMORY_WORKSPACE"

LOCAL, HONCHO, MEM0 = "local", "honcho", "mem0"
PROVIDERS = (LOCAL, HONCHO, MEM0)
DEFAULT_USER = "marvi-user"
DEFAULT_WORKSPACE = "marvi-os"
DEFAULT_HONCHO_URL = "https://api.honcho.dev"


@runtime_checkable
class MemoryProvider(Protocol):
    def observe(self, user: str, assistant: str) -> None: ...

    def recall_block(self, text: str, limit: int, budget: int) -> str: ...

    def recent(self, limit: int) -> list[dict[str, Any]]: ...

    def forget(self, memory_id: str) -> bool: ...

    def forget_all(self) -> int: ...


def _bounded_line_block(rows: list[dict[str, Any]], budget: int) -> str:
    lines: list[str] = []
    spent = 0
    for row in rows:
        subject = str(row.get("subject") or "").strip()
        body = str(row.get("body") or "").strip()
        text = body or subject
        if not text:
            continue
        line = f"- {subject}: {body}" if subject and body else f"- {text}"
        if spent + len(line) > budget:
            break
        lines.append(line)
        spent += len(line)
    if not lines:
        return ""
    return (
        "# What you remember\n\n"
        + "\n".join(lines)
        + "\n\nYour own notes from earlier. They may be out of date; prefer what "
        "the user says now, and do not repeat them back unprompted."
    )


def _provider_block(provider: str, rows: list[dict[str, Any]], budget: int) -> str:
    """Keep provider output in data position, even when its text is malicious."""
    block = _bounded_line_block(rows, budget)
    return wrap_external(f"memory:{provider}", block).text if block else ""


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


class LocalMemoryProvider:
    """The existing SQLite store as the first provider implementation."""

    name = LOCAL

    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or MemoryStore()
        self._observer: Callable[[str, str], Any] | None = None

    def bind_observer(self, observer: Callable[[str, str], Any]) -> None:
        self._observer = observer

    def observe(self, user: str, assistant: str) -> None:
        if self._observer is None:
            raise RuntimeError("local memory extraction is not ready")
        self._observer(user, assistant)

    def recall_block(self, text: str, limit: int = 5, budget: int = 1_200) -> str:
        return self.store.recall_block(text, limit=limit, budget=budget)

    def recent(self, limit: int) -> list[dict[str, Any]]:
        return self.store.recent(limit=limit)

    def search(self, text: str, limit: int = 5) -> list[dict[str, Any]]:
        return self.store.search(text, limit=limit)

    def remember_explicit(self, subject: str, body: str, **kwargs: Any) -> str:
        return str(self.store.remember(subject, body, **kwargs))

    def remember_external(self, subject: str, body: str, source: str, **kwargs: Any) -> str:
        return str(self.store.remember_external(subject, body, source, **kwargs))

    def forget(self, memory_id: str) -> bool:
        return self.store.forget(memory_id)

    def forget_all(self) -> int:
        return self.store.forget_all()

    def forget_by_source(self, source: str) -> int:
        return self.store.forget_by_source(source)


class Mem0Provider:
    """Mem0 adapter for managed, self-hosted, or pinned in-process OSS use."""

    name = MEM0

    def __init__(
        self,
        *,
        api_key: str = "",
        url: str = "",
        user_id: str = DEFAULT_USER,
        client: Any = None,
    ) -> None:
        self.user_id = user_id
        self._client = client
        self._api_key = api_key
        self._url = url.rstrip("/")

    def _memory(self) -> Any:
        if self._client is not None:
            return self._client
        if self._url.lower() in {"local", "oss", "in-process"}:
            from mem0 import Memory

            self._client = Memory()
        elif self._url:
            self._client = _Mem0RestClient(self._url, self._api_key)
        else:
            from mem0 import MemoryClient

            self._client = MemoryClient(
                api_key=self._api_key,
            )
        return self._client

    @staticmethod
    def _results(result: Any) -> list[Any]:
        if isinstance(result, dict):
            found = result.get("results", [])
            return found if isinstance(found, list) else []
        return result if isinstance(result, list) else []

    @staticmethod
    def _row(item: Any) -> dict[str, Any]:
        content = str(_value(item, "memory", _value(item, "text", "")) or "")
        return {
            "id": str(_value(item, "id", "")),
            "kind": "semantic",
            "subject": content,
            "body": "",
            "source": MEM0,
            "trusted": "[UNTRUSTED EXTERNAL DATA" not in content,
            "at": str(_value(item, "updated_at", _value(item, "created_at", "")) or ""),
            **({"score": _value(item, "score")} if _value(item, "score") is not None else {}),
        }

    def observe(self, user: str, assistant: str) -> None:
        messages = [
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ]
        try:
            self._memory().add(messages, user_id=self.user_id, async_mode=False)
        except TypeError:
            # The in-process OSS object is synchronous and has no async_mode;
            # the managed client accepts it to make extraction deterministic.
            self._memory().add(messages, user_id=self.user_id)

    def search(self, text: str, limit: int = 5) -> list[dict[str, Any]]:
        try:
            result = self._memory().search(text, user_id=self.user_id, top_k=limit)
        except TypeError:
            result = self._memory().search(text, user_id=self.user_id, limit=limit)
        return [self._row(item) for item in self._results(result)[:limit]]

    def recall_block(self, text: str, limit: int = 5, budget: int = 1_200) -> str:
        if not text.strip():
            return ""
        try:
            return _provider_block(MEM0, self.search(text, limit), budget)
        except Exception as exc:  # provider outages must not block a reply
            log.warning("Mem0 recall unavailable: %s", exc)
            return ""

    def recent(self, limit: int) -> list[dict[str, Any]]:
        try:
            result = self._memory().get_all(user_id=self.user_id, top_k=limit)
        except TypeError:
            result = self._memory().get_all(user_id=self.user_id, limit=limit)
        return [self._row(item) for item in self._results(result)[:limit]]

    def remember_explicit(self, subject: str, body: str, **_: Any) -> str:
        text = f"{subject}: {body}" if body else subject
        try:
            result = self._memory().add(text, user_id=self.user_id, infer=False, async_mode=False)
        except TypeError:
            result = self._memory().add(text, user_id=self.user_id, infer=False)
        rows = self._results(result)
        return str(_value(rows[0], "id", "")) if rows else ""

    def remember_external(self, subject: str, body: str, source: str, **_: Any) -> str:
        # The explicit provenance and warning survive provider extraction.
        return self.remember_explicit(
            subject,
            f"[UNTRUSTED EXTERNAL DATA from {source}] {body} [END EXTERNAL DATA]",
        )

    def forget(self, memory_id: str) -> bool:
        try:
            self._memory().delete(memory_id)
            return True
        except Exception as exc:
            log.warning("Mem0 could not forget %s: %s", memory_id, exc)
            return False

    def forget_all(self) -> int:
        count = len(self.recent(1000))
        self._memory().delete_all(user_id=self.user_id)
        return count


class _Mem0RestClient:
    """Thin adapter for the official self-hosted OSS REST surface.

    Self-hosted Mem0 intentionally has no ``/v1`` prefix and authenticates
    programmatic clients with ``X-API-Key``. The managed SDK uses different
    paths and an Authorization token, so pointing it at an OSS URL is not a
    supported shortcut.
    """

    def __init__(self, url: str, api_key: str, client: httpx.Client | None = None) -> None:
        headers = {"X-API-Key": api_key} if api_key else {}
        self.client = client or httpx.Client(base_url=url.rstrip("/"), headers=headers, timeout=300)

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        response.raise_for_status()
        return response.json() if response.content else {}

    def add(self, messages: Any, **kwargs: Any) -> Any:
        payload = {"messages": messages, **kwargs}
        payload.pop("async_mode", None)
        return self._json(self.client.post("/memories", json=payload))

    def search(self, query: str, **kwargs: Any) -> Any:
        top_k = kwargs.pop("top_k", kwargs.pop("limit", None))
        payload = {"query": query, **kwargs}
        if top_k is not None:
            payload["limit"] = top_k
        return self._json(self.client.post("/search", json=payload))

    def get_all(self, **kwargs: Any) -> Any:
        limit = kwargs.pop("top_k", kwargs.pop("limit", None))
        if limit is not None:
            kwargs["limit"] = limit
        return self._json(self.client.get("/memories", params=kwargs))

    def delete(self, memory_id: str) -> Any:
        return self._json(self.client.delete(f"/memories/{memory_id}"))

    def delete_all(self, **kwargs: Any) -> Any:
        return self._json(self.client.delete("/memories", params=kwargs))


class HonchoProvider:
    """Honcho adapter using separate user/assistant peers and one session."""

    name = HONCHO

    def __init__(
        self,
        *,
        api_key: str = "",
        url: str = DEFAULT_HONCHO_URL,
        user_id: str = DEFAULT_USER,
        workspace_id: str = DEFAULT_WORKSPACE,
        client: Any = None,
    ) -> None:
        self.user_id = user_id
        self.assistant_id = "marvi"
        self.workspace_id = workspace_id
        self.session_id = f"{user_id}-marvi"
        self._api_key = api_key
        self._url = url.rstrip("/") or DEFAULT_HONCHO_URL
        self._client = client
        self._user: Any = None
        self._assistant: Any = None
        self._session: Any = None

    def _resources(self) -> tuple[Any, Any, Any]:
        if self._session is None:
            if self._client is None:
                from honcho import Honcho

                self._client = Honcho(
                    workspace_id=self.workspace_id,
                    api_key=self._api_key or None,
                    base_url=self._url,
                )
            self._user = self._client.peer(self.user_id)
            self._assistant = self._client.peer(self.assistant_id)
            self._session = self._client.session(self.session_id)
        return self._user, self._assistant, self._session

    @staticmethod
    def _row(item: Any) -> dict[str, Any]:
        content = str(_value(item, "content", "") or "")
        return {
            "id": str(_value(item, "id", "")),
            "kind": "semantic",
            "subject": content,
            "body": "",
            "source": HONCHO,
            "trusted": "[UNTRUSTED EXTERNAL DATA" not in content,
            "at": str(_value(item, "created_at", "") or ""),
        }

    def _conclusions(self) -> Any:
        user, _, _ = self._resources()
        return user.conclusions

    def observe(self, user: str, assistant: str) -> None:
        user_peer, assistant_peer, session = self._resources()
        # Attribution is essential to the Deriver: never concatenate a turn.
        session.add_messages([user_peer.message(user), assistant_peer.message(assistant)])

    def search(self, text: str, limit: int = 5) -> list[dict[str, Any]]:
        return [self._row(item) for item in self._conclusions().query(text, top_k=limit)]

    def recall_block(self, text: str, limit: int = 5, budget: int = 1_200) -> str:
        if not text.strip():
            return ""
        try:
            user, _, session = self._resources()
            context = session.context(
                summary=True,
                peer_target=user.id,
                search_query=text,
                search_top_k=limit,
                max_conclusions=max(limit, 10),
            )
            rows = [{"subject": item} for item in (_value(context, "peer_card", []) or [])]
            summary = _value(context, "summary")
            summary_text = str(_value(summary, "content", "") or "").strip()
            if summary_text:
                rows.append({"subject": "Session summary", "body": summary_text})
            representation = str(_value(context, "peer_representation", "") or "").strip()
            if representation:
                rows.append({"subject": "Current representation", "body": representation})
            return _provider_block(HONCHO, rows, budget)
        except Exception as exc:  # provider outages must not block a reply
            log.warning("Honcho recall unavailable: %s", exc)
            return ""

    def recent(self, limit: int) -> list[dict[str, Any]]:
        return [self._row(item) for item in list(self._conclusions().list(reverse=True))[:limit]]

    def remember_explicit(self, subject: str, body: str, **_: Any) -> str:
        _, _, session = self._resources()
        made = self._conclusions().create(
            [{"content": f"{subject}: {body}" if body else subject, "session_id": session.id}]
        )
        return str(_value(made[0], "id", "")) if made else ""

    def remember_external(self, subject: str, body: str, source: str, **_: Any) -> str:
        return self.remember_explicit(
            subject,
            f"[UNTRUSTED EXTERNAL DATA from {source}] {body} [END EXTERNAL DATA]",
        )

    def forget(self, memory_id: str) -> bool:
        try:
            self._conclusions().delete(memory_id)
            return True
        except Exception as exc:
            log.warning("Honcho could not forget %s: %s", memory_id, exc)
            return False

    def forget_all(self) -> int:
        rows = self.recent(1000)
        for row in rows:
            self._conclusions().delete(row["id"])
        user, _, session = self._resources()
        user.set_card([])
        session.delete()
        self._session = None
        return len(rows)


class MemoryRuntime:
    """Compatibility facade that switches the one active provider live."""

    DREAMT = MemoryStore.DREAMT

    def __init__(self, local: LocalMemoryProvider | None = None) -> None:
        self.local = local or LocalMemoryProvider()
        self._external: tuple[tuple[str, ...], MemoryProvider] | None = None

    @property
    def path(self):
        return self.local.store.path if self.provider_name == LOCAL else None

    @property
    def provider_name(self) -> str:
        selected = os.environ.get(PROVIDER_SETTING, LOCAL).strip().lower() or LOCAL
        return selected if selected in PROVIDERS else LOCAL

    def bind_local_observer(self, observer: Callable[[str, str], Any]) -> None:
        self.local.bind_observer(observer)

    def _provider(self) -> MemoryProvider:
        selected = self.provider_name
        if selected == LOCAL:
            return self.local
        key = os.environ.get(KEY_SETTING, "").strip()
        url = os.environ.get(URL_SETTING, "").strip()
        user = os.environ.get(USER_SETTING, DEFAULT_USER).strip() or DEFAULT_USER
        workspace = (
            os.environ.get(WORKSPACE_SETTING, DEFAULT_WORKSPACE).strip() or DEFAULT_WORKSPACE
        )
        fingerprint = (selected, url, key, user, workspace)
        if self._external and self._external[0] == fingerprint:
            return self._external[1]
        provider: MemoryProvider
        if selected == HONCHO:
            provider = HonchoProvider(
                api_key=key,
                url=url or DEFAULT_HONCHO_URL,
                user_id=user,
                workspace_id=workspace,
            )
        else:
            provider = Mem0Provider(api_key=key, url=url, user_id=user)
        self._external = (fingerprint, provider)
        return provider

    def observe(self, user: str, assistant: str) -> None:
        self._provider().observe(user, assistant)

    def recall_block(self, text: str, limit: int = 5, budget: int = 1_200) -> str:
        return self._provider().recall_block(text, limit, budget)

    def recent(self, limit: int = 10, kind: str | None = None) -> list[dict[str, Any]]:
        try:
            rows = self._provider().recent(limit)
        except Exception as exc:
            log.warning("%s memory listing unavailable: %s", self.provider_name, exc)
            return []
        return [row for row in rows if kind is None or row.get("kind") == kind]

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        provider = self._provider()
        search = getattr(provider, "search", None)
        if not callable(search):
            return []
        try:
            return search(query, limit)
        except Exception as exc:
            log.warning("%s memory search unavailable: %s", self.provider_name, exc)
            return []

    def remember(self, subject: str, body: str, kind: str = "episodic", **kwargs: Any) -> str:
        provider = self._provider()
        remember = provider.remember_explicit  # type: ignore[attr-defined]
        return remember(subject, body, kind=kind, **kwargs)

    def remember_external(self, subject: str, body: str, source: str, **kwargs: Any) -> str:
        provider = self._provider()
        remember = provider.remember_external  # type: ignore[attr-defined]
        return remember(subject, body, source, **kwargs)

    def forget(self, memory_id: str) -> bool:
        return self._provider().forget(str(memory_id))

    def forget_matching(self, query: str) -> int:
        rows = self.search(query, 100)
        return sum(1 for row in rows if self.forget(str(row["id"])))

    def forget_all(self) -> int:
        return self._provider().forget_all()

    def forget_by_source(self, source: str) -> int:
        """Retract everything one connection wrote, for disconnect.

        Only the local provider can do this exactly: it stores `source` as a
        column. Honcho and Mem0 own extraction themselves and never surfaced
        a source-addressable delete, so under an external provider this is a
        reported gap rather than a silent no-op that pretends to have
        cleaned up — see RFC-NATIVE-CONNECTORS-REVIEW.md, "disconnect does
        not retract what was ingested".
        """
        if self.provider_name != LOCAL:
            log.warning(
                "cannot retract by source under %s; disconnecting will not"
                " remove memories already written to it",
                self.provider_name,
            )
            return 0
        return self.local.store.forget_by_source(source)

    def count(self) -> int:
        if self.provider_name == LOCAL:
            return self.local.store.count()
        return len(self.recent(1000))

    def export(self) -> list[dict[str, Any]]:
        if self.provider_name == LOCAL:
            return self.local.store.export()
        return self.recent(1000)

    def world_summary(self, limit: int = 5) -> dict[str, Any]:
        if self.provider_name == LOCAL:
            return self.local.store.world_summary(limit)
        rows = self.recent(limit)
        return {
            "total": self.count(),
            "facts": [str(row.get("subject") or "") for row in rows],
            "recent_events": [],
            "graph": {"entities": 0, "relations": 0},
        }

    def graph_export(self, mode: str = "tree", limit: int = 1000) -> dict[str, Any]:
        if self.provider_name == LOCAL:
            return self.local.store.graph_export(mode, limit)
        if mode == "contacts":
            return {"mode": mode, "nodes": [], "edges": []}
        rows = self.recent(limit)
        if not rows:
            return {"mode": mode, "nodes": [], "edges": []}
        source = self.provider_name
        nodes = [
            {"id": "arc:memory", "kind": "root", "label": "Memory", "level": 2},
            {"id": f"source:{source}", "kind": "source", "label": source, "level": 1},
        ]
        edges = [
            {"id": f"arc:source:{source}", "source": "arc:memory", "target": f"source:{source}"}
        ]
        for row in rows:
            node_id = f"memory:{row['id']}"
            nodes.append(
                {
                    "id": node_id,
                    "kind": "summary",
                    "label": row.get("subject") or row.get("body") or "Memory",
                    "level": 0,
                    "memory_kind": "semantic",
                    "trusted": bool(row.get("trusted", True)),
                    "provenance": source,
                    "at": row.get("at", ""),
                }
            )
            edges.append({"id": f"arc:{node_id}", "source": f"source:{source}", "target": node_id})
        return {"mode": mode, "nodes": nodes, "edges": edges}

    # Provider-owned consolidation replaces the local reflection passes.
    def reflect(self, summarise: Any = None, limit: int = 50) -> dict[str, Any]:
        if self.provider_name == LOCAL:
            return self.local.store.reflect(summarise=summarise, limit=limit)
        return {"considered": 0, "promoted": []}

    def consolidate(self) -> dict[str, int]:
        if self.provider_name == LOCAL:
            return self.local.store.consolidate()
        return {"forgotten": 0, "orphan_entities": 0}

    def index_missing(self, limit: int = 1000) -> int:
        return self.local.store.index_missing(limit) if self.provider_name == LOCAL else 0

    def conclude(self, subject: str, body: str, premises: list[str]) -> str:
        if self.provider_name == LOCAL:
            return str(self.local.store.conclude(subject, body, premises))
        return self.remember(subject, body, kind="semantic")

    def link(self, subject: str, predicate: str, target: str, **kwargs: Any) -> str:
        if self.provider_name == LOCAL:
            return str(self.local.store.link(subject, predicate, target, **kwargs))
        return ""

    def neighbours(self, name: str) -> list[dict[str, Any]]:
        return self.local.store.neighbours(name) if self.provider_name == LOCAL else []

    def retire(self, memory_id: str) -> bool:
        return (
            self.local.store.retire(memory_id)
            if self.provider_name == LOCAL
            else self.forget(memory_id)
        )

    def undreamt(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.local.store.undreamt(limit) if self.provider_name == LOCAL else []

    def conclusions(self) -> list[dict[str, Any]]:
        return self.local.store.conclusions() if self.provider_name == LOCAL else []

    def record_dream(self, **kwargs: Any) -> None:
        if self.provider_name == LOCAL:
            self.local.store.record_dream(**kwargs)

    def forget_imported_sources(self) -> None:
        if self.provider_name == LOCAL:
            self.local.store.forget_imported_sources()

    def close(self) -> None:
        self.local.store.close()


def describe() -> dict[str, Any]:
    selected = os.environ.get(PROVIDER_SETTING, LOCAL).strip().lower() or LOCAL
    if selected not in PROVIDERS:
        selected = LOCAL
    url = os.environ.get(URL_SETTING, "").strip()
    key = os.environ.get(KEY_SETTING, "").strip()
    return {
        "provider": selected,
        "providers": list(PROVIDERS),
        "url": url,
        "key_set": bool(key),
        "user_id": os.environ.get(USER_SETTING, DEFAULT_USER).strip() or DEFAULT_USER,
        "workspace": os.environ.get(WORKSPACE_SETTING, DEFAULT_WORKSPACE).strip()
        or DEFAULT_WORKSPACE,
    }
