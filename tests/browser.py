"""Helpers for tests that need a real Chromium (skipped when none can be launched)."""

import pytest
from playwright.async_api import async_playwright

from brandguard.pipeline.crawl.browser import chromium_executable


async def launch(playwright):
    try:
        return await playwright.chromium.launch(executable_path=chromium_executable())
    except Exception as exc:  # no browser installed on this machine
        pytest.skip(f"Chromium not available: {exc}")


__all__ = ["async_playwright", "launch"]


def require_chromium() -> None:
    """Skip the calling test when no Chromium can be launched."""
    import asyncio

    async def check():
        async with async_playwright() as playwright:
            await (await launch(playwright)).close()

    asyncio.run(check())
