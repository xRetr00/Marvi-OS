"""Web search, fetch, and extraction.

Providers are selected from the environment in a fixed order, the same shape
Hermes uses: whichever key is present wins, and the absence of every key is a
clear "not configured" rather than a crash.

Everything the web returns is somebody else's writing, so every result leaves
this module inside an `untrusted.wrap_external` envelope. Nothing here executes
anything, follows a redirect off-protocol, or reaches a private address.
"""

from __future__ import annotations

import contextlib
import ipaddress
import os
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx

from .untrusted import wrap_external

REQUEST_TIMEOUT = 15.0
MAX_FETCH_BYTES = 2_000_000
DEFAULT_RESULTS = 5

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


class WebUnavailableError(Exception):
    """No search provider is configured."""


class WebRefusedError(Exception):
    """The request was refused before leaving the machine."""


# -- SSRF guard -------------------------------------------------------------


def assert_public_http_url(url: str) -> str:
    """Refuse anything that is not a public http(s) URL.

    An agent that can be told to fetch a URL can be told to fetch
    `http://127.0.0.1:17842` or a cloud metadata endpoint. Resolve first, then
    decide — a hostname can point anywhere.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise WebRefusedError(f"only http and https are allowed, not {parsed.scheme or 'nothing'}")
    if not parsed.hostname:
        raise WebRefusedError("that URL has no host")

    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except OSError as exc:
        raise WebRefusedError(f"could not resolve {parsed.hostname}") from exc

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise WebRefusedError(
                f"{parsed.hostname} resolves to the private address {address}; refused"
            )
    return url


# -- HTML to text -----------------------------------------------------------


SKIP_TAGS: frozenset[str] = frozenset({"script", "style", "noscript", "template", "svg"})


class _TextExtractor(HTMLParser):
    SKIP = SKIP_TAGS

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title and not self.title:
            self.title = text
        else:
            self.parts.append(text)


def html_to_text(html: str) -> tuple[str, str]:
    parser = _TextExtractor()
    with contextlib.suppress(Exception):
        # Malformed markup is normal on the web; keep whatever parsed.
        parser.feed(html)
    return parser.title, "\n".join(parser.parts)


# -- providers --------------------------------------------------------------


def configured_provider() -> str | None:
    """First configured provider wins. Mirrors the Hermes selection order."""
    if os.environ.get("SEARXNG_URL", "").strip():
        return "searxng"
    if os.environ.get("BRAVE_SEARCH_API_KEY", "").strip():
        return "brave"
    return None


class WebTools:
    def __init__(self, client: httpx.Client | None = None, provider: str | None = None) -> None:
        self._client = client
        self._provider = provider

    def provider(self) -> str | None:
        return self._provider or configured_provider()

    def _http(self) -> httpx.Client:
        return self._client or httpx.Client(
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
            headers={"user-agent": "MarviOS/0.1 (+local assistant)"},
        )

    def _close(self, client: httpx.Client) -> None:
        if self._client is None:
            client.close()

    # -- search ---------------------------------------------------------

    def search(self, query: str, limit: int = DEFAULT_RESULTS) -> list[dict[str, Any]]:
        provider = self.provider()
        if provider is None:
            raise WebUnavailableError(
                "No web search provider configured. Set BRAVE_SEARCH_API_KEY or SEARXNG_URL."
            )
        limit = max(1, min(limit, 20))
        client = self._http()
        try:
            if provider == "brave":
                response = client.get(
                    BRAVE_ENDPOINT,
                    params={"q": query, "count": limit},
                    headers={
                        "accept": "application/json",
                        "x-subscription-token": os.environ["BRAVE_SEARCH_API_KEY"].strip(),
                    },
                )
                response.raise_for_status()
                results = (response.json().get("web") or {}).get("results") or []
                return [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("description", ""),
                    }
                    for r in results[:limit]
                ]

            base = os.environ["SEARXNG_URL"].strip().rstrip("/")
            response = client.get(
                f"{base}/search", params={"q": query, "format": "json"}
            )
            response.raise_for_status()
            results = response.json().get("results") or []
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content", ""),
                }
                for r in results[:limit]
            ]
        except httpx.HTTPError as exc:
            raise WebUnavailableError(f"{provider} search failed: {exc}") from exc
        finally:
            self._close(client)

    # -- fetch and extract ----------------------------------------------

    def fetch(self, url: str) -> dict[str, Any]:
        """Raw-ish retrieval: status, content type, and a bounded body."""
        assert_public_http_url(url)
        client = self._http()
        try:
            response = client.get(url)
            body = response.content[:MAX_FETCH_BYTES]
            return {
                "url": str(response.url),
                "status": response.status_code,
                "content_type": response.headers.get("content-type", ""),
                "truncated": len(response.content) > MAX_FETCH_BYTES,
                "body": body.decode(response.encoding or "utf-8", "replace"),
            }
        except httpx.HTTPError as exc:
            raise WebUnavailableError(f"could not fetch {url}: {exc}") from exc
        finally:
            self._close(client)

    def extract(self, url: str) -> dict[str, Any]:
        """Readable text for a page, which is what a voice assistant needs."""
        page = self.fetch(url)
        title, text = html_to_text(page["body"])
        return {
            "url": page["url"],
            "status": page["status"],
            "title": title,
            "text": text,
            "truncated": page["truncated"],
        }


def register_web_tools(registry, web: WebTools) -> None:
    """Reads only. None of these are sensitive, and all are enveloped."""
    from .tools import ToolSpec

    def web_search(query: str, limit: int = DEFAULT_RESULTS) -> dict[str, Any]:
        results = web.search(query, limit)
        return wrap_external(f"web:search:{web.provider()}", results).model_dump()

    def web_extract(url: str) -> dict[str, Any]:
        return wrap_external(f"web:{url}", web.extract(url)).model_dump()

    def web_fetch(url: str) -> dict[str, Any]:
        return wrap_external(f"web:{url}", web.fetch(url)).model_dump()

    registry.register(
        ToolSpec(
            name="web_search",
            description="Search the web",
            arguments={"query": str},
            optional={"limit": int},
            sensitive=False,
            handler=web_search,
        )
    )
    registry.register(
        ToolSpec(
            name="web_extract",
            description="Read the text of a web page",
            arguments={"url": str},
            sensitive=False,
            handler=web_extract,
        )
    )
    registry.register(
        ToolSpec(
            name="web_fetch",
            description="Fetch a URL exactly as served",
            arguments={"url": str},
            sensitive=False,
            handler=web_fetch,
        )
    )
