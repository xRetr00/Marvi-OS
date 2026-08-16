"""Browser tools and automation.

A single long-lived Playwright page, driven from synchronous tool handlers via
the shared background loop. One page rather than a pool: a voice assistant is
doing one thing at a time, and a pool would need a session concept the user
never asked for.

The safety shape follows ADR-016:

* navigation is SSRF-guarded exactly like `web_fetch`, so the browser cannot be
  talked into loading loopback or a cloud metadata endpoint;
* whatever a page says is untrusted content and leaves here enveloped — a
  browsing agent reading an attacker-authored page is the textbook injection
  path, and the page is *more* dangerous than a fetched document because the
  agent can also act on it;
* reading is ungated; clicking, typing, and submitting are sensitive, so they
  inherit the confirmation token and the audit trail;
* downloads are refused outright rather than confirmed.
"""

from __future__ import annotations

import os
from typing import Any

from .background import LoopThread
from .untrusted import wrap_external
from .web import assert_public_http_url

NAV_TIMEOUT_MS = 30_000
ACTION_TIMEOUT_MS = 15_000
MAX_PAGE_CHARS = 12_000
LAUNCH_TIMEOUT = 90.0


class BrowserUnavailableError(Exception):
    """Playwright is not installed, or no browser could be launched."""


class BrowserRefusedError(Exception):
    """The request was refused before the browser acted."""


def browser_enabled() -> bool:
    """Off unless asked for: a headless browser is a real resource cost."""
    return os.environ.get("MARVI_BROWSER", "").strip().lower() in ("1", "true", "on", "yes")


class BrowserSession:
    """One page, launched on first use and reused afterwards."""

    def __init__(self, headless: bool = True, loop: LoopThread | None = None) -> None:
        self.headless = headless
        self._loop = loop
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None

    # -- lifecycle ----------------------------------------------------------

    def _ensure_loop(self) -> LoopThread:
        if self._loop is None:
            self._loop = LoopThread(name="marvi-browser")
        return self._loop

    async def _launch(self) -> Any:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserUnavailableError("Playwright is not installed.") from exc

        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch(headless=self.headless)
        except Exception as exc:
            raise BrowserUnavailableError(f"could not launch Chromium: {exc}") from exc
        context = await self._browser.new_context(accept_downloads=False)
        context.set_default_timeout(ACTION_TIMEOUT_MS)
        page = await context.new_page()
        # A download is a file arriving from an untrusted source; refuse rather
        # than ask, matching the file-handling rules.
        page.on("download", lambda download: download.cancel())
        page.on("dialog", lambda dialog: dialog.dismiss())
        return page

    def _current(self) -> Any:
        if self._page is None:
            self._page = self._ensure_loop().submit(self._launch(), timeout=LAUNCH_TIMEOUT)
        return self._page

    def close(self) -> dict[str, Any]:
        if self._page is None:
            return {"closed": False}
        loop = self._ensure_loop()

        async def shutdown() -> None:
            if self._browser is not None:
                await self._browser.close()
            if self._playwright is not None:
                await self._playwright.stop()

        try:
            loop.submit(shutdown())
        finally:
            self._page = None
            self._browser = None
            self._playwright = None
            loop.stop()
            self._loop = None
        return {"closed": True}

    # -- reading ------------------------------------------------------------

    async def _snapshot(self, page: Any) -> dict[str, Any]:
        try:
            text = await page.inner_text("body")
        except Exception:
            text = ""
        return {
            "url": page.url,
            "title": await page.title(),
            "text": text[:MAX_PAGE_CHARS],
            "truncated": len(text) > MAX_PAGE_CHARS,
        }

    def open(self, url: str) -> dict[str, Any]:
        assert_public_http_url(url)
        page = self._current()

        async def go() -> dict[str, Any]:
            await page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
            return await self._snapshot(page)

        return self._ensure_loop().submit(go(), timeout=LAUNCH_TIMEOUT)

    def read(self) -> dict[str, Any]:
        page = self._require_page()
        return self._ensure_loop().submit(self._snapshot(page))

    def links(self, limit: int = 40) -> list[dict[str, str]]:
        page = self._require_page()

        async def collect() -> list[dict[str, str]]:
            found = await page.eval_on_selector_all(
                "a[href]",
                "els => els.slice(0, 200).map(e => ({text: (e.innerText||'').trim(), href: e.href}))",
            )
            return [link for link in found if link.get("href")][: max(1, min(limit, 200))]

        return self._ensure_loop().submit(collect())

    def _require_page(self) -> Any:
        if self._page is None:
            raise BrowserRefusedError("No page is open. Open a URL first.")
        return self._page

    # -- acting -------------------------------------------------------------

    def click(self, selector: str) -> dict[str, Any]:
        page = self._require_page()

        async def act() -> dict[str, Any]:
            await page.click(selector, timeout=ACTION_TIMEOUT_MS)
            await page.wait_for_load_state("domcontentloaded")
            return await self._snapshot(page)

        return self._ensure_loop().submit(act())

    def type_text(self, selector: str, text: str, submit: bool = False) -> dict[str, Any]:
        page = self._require_page()

        async def act() -> dict[str, Any]:
            await page.fill(selector, text, timeout=ACTION_TIMEOUT_MS)
            if submit:
                await page.press(selector, "Enter")
                await page.wait_for_load_state("domcontentloaded")
            return await self._snapshot(page)

        return self._ensure_loop().submit(act())

    def back(self) -> dict[str, Any]:
        page = self._require_page()

        async def act() -> dict[str, Any]:
            await page.go_back(timeout=NAV_TIMEOUT_MS)
            return await self._snapshot(page)

        return self._ensure_loop().submit(act())

    def screenshot(self, path: str) -> dict[str, Any]:
        page = self._require_page()

        async def act() -> dict[str, Any]:
            await page.screenshot(path=path, full_page=False)
            return {"path": path}

        return self._ensure_loop().submit(act())


def register_browser_tools(registry, session: BrowserSession, workspace: Any = None) -> None:
    """Reads ungated and enveloped; interactions sensitive."""
    from .tools import ToolSpec

    def envelope(snapshot: dict[str, Any]) -> dict[str, Any]:
        payload = wrap_external(f"browser:{snapshot.get('url', '')}", snapshot).model_dump()
        payload["url"] = snapshot.get("url", "")
        payload["title"] = snapshot.get("title", "")
        return payload

    def browser_open(url: str) -> dict[str, Any]:
        return envelope(session.open(url))

    def browser_read() -> dict[str, Any]:
        return envelope(session.read())

    def browser_links(limit: int = 40) -> dict[str, Any]:
        return wrap_external("browser:links", session.links(limit)).model_dump()

    def browser_click(selector: str) -> dict[str, Any]:
        return envelope(session.click(selector))

    def browser_type(selector: str, text: str, submit: bool = False) -> dict[str, Any]:
        return envelope(session.type_text(selector, text, submit))

    def browser_back() -> dict[str, Any]:
        return envelope(session.back())

    def browser_screenshot(path: str = "browser.png") -> dict[str, Any]:
        if workspace is None or not workspace.available():
            raise BrowserRefusedError(
                "Screenshots need a workspace root; set MARVI_WORKSPACE_ROOT."
            )
        target = workspace.resolve(path)
        return session.screenshot(str(target))

    def browser_close() -> dict[str, Any]:
        return session.close()

    for spec in (
        ToolSpec(
            name="browser_open", description="Open a web page in the browser",
            arguments={"url": str}, sensitive=False, handler=browser_open,
        ),
        ToolSpec(
            name="browser_read", description="Read the current page",
            arguments={}, sensitive=False, handler=browser_read,
        ),
        ToolSpec(
            name="browser_links", description="List links on the current page",
            arguments={}, optional={"limit": int}, sensitive=False, handler=browser_links,
        ),
        ToolSpec(
            name="browser_click", description="Click something on the page",
            arguments={"selector": str}, sensitive=True, handler=browser_click,
        ),
        ToolSpec(
            name="browser_type", description="Type into a field on the page",
            arguments={"selector": str, "text": str}, optional={"submit": bool},
            sensitive=True, handler=browser_type,
        ),
        ToolSpec(
            name="browser_back", description="Go back to the previous page",
            arguments={}, sensitive=False, handler=browser_back,
        ),
        ToolSpec(
            name="browser_screenshot", description="Save a screenshot of the page",
            arguments={}, optional={"path": str}, sensitive=False, handler=browser_screenshot,
        ),
        ToolSpec(
            name="browser_close", description="Close the browser",
            arguments={}, sensitive=False, handler=browser_close,
        ),
    ):
        registry.register(spec)
