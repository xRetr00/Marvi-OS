"""Setup health check: launch the cached engine, not just its CLI."""

import asyncio


async def check():
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, timeout=20_000)
        try:
            page = await browser.new_page()
            await page.goto("about:blank")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(check())
