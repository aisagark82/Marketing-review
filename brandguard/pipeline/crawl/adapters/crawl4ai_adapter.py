"""Crawl4AI (Apache-2.0) connected over CDP to a Chromium that BrandGuard launches itself.

Why not let Crawl4AI launch the browser: it always adds --disable-blink-features=
AutomationControlled (which hides that the browser is automated) and
--ignore-certificate-errors, with no option to turn either off. Both conflict with the
independent-test policy (design §8.1), so we start Chromium with plain flags and certificate
checks on, and Crawl4AI only drives pages. Its stealth, "magic", navigator overrides, user
simulation and overlay removal stay off.
"""

import asyncio
import importlib.metadata
import shutil
import subprocess
import tempfile
from collections import deque
from pathlib import Path

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
from playwright.async_api import async_playwright

from brandguard.pipeline.crawl.adapters import BrowserSettings
from brandguard.pipeline.crawl.browser import running_as_root
from brandguard.pipeline.crawl.capture import VIEWPORT, RequestFilter, capture_page
from brandguard.pipeline.crawl.recorder import CrawlSink

STARTUP_TIMEOUT_S = 30


class LaunchedChromium:
    """A headless Chromium with a DevTools port, started with only ordinary flags."""

    def __init__(self, executable: str, user_agent: str, javascript: bool):
        self.profile = tempfile.mkdtemp(prefix="brandguard-chromium-")
        args = [
            executable,
            "--headless=new",
            "--remote-debugging-port=0",
            f"--user-data-dir={self.profile}",
            f"--user-agent={user_agent}",
            f"--window-size={VIEWPORT['width']},{VIEWPORT['height']}",
            "--no-first-run",
            "--no-default-browser-check",
            "--mute-audio",
            "--hide-scrollbars",
        ]
        if running_as_root():
            args.append("--no-sandbox")
        if not javascript:
            args.append("--blink-settings=scriptEnabled=false")
        self.process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    async def cdp_url(self) -> str:
        port_file = Path(self.profile) / "DevToolsActivePort"
        for _ in range(STARTUP_TIMEOUT_S * 10):
            if port_file.exists():
                lines = port_file.read_text().split()
                if lines:
                    return f"http://127.0.0.1:{lines[0]}"
            if self.process.poll() is not None:
                raise RuntimeError(f"Chromium exited with code {self.process.returncode}")
            await asyncio.sleep(0.1)
        raise RuntimeError("Chromium did not open its DevTools port in time")

    def close(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


async def _default_chromium() -> str:
    async with async_playwright() as playwright:
        return playwright.chromium.executable_path


class Crawl4AIAdapter:
    name = "crawl4ai"

    def version(self) -> str:
        return importlib.metadata.version("crawl4ai")

    async def run(self, seeds: list[str], sink: CrawlSink, browser: BrowserSettings) -> None:
        executable = browser.executable_path or await _default_chromium()
        chromium = LaunchedChromium(executable, browser.user_agent, browser.javascript)
        try:
            config = BrowserConfig(
                cdp_url=await chromium.cdp_url(),
                ignore_https_errors=False,
                # Crawl4AI otherwise sets its own default User-Agent on the pages it opens.
                user_agent=browser.user_agent,
                user_agent_mode="",
                viewport_width=VIEWPORT["width"],
                viewport_height=VIEWPORT["height"],
                verbose=False,
            )
            async with AsyncWebCrawler(config=config) as crawler:
                await self._crawl(crawler, seeds, sink, browser)
        finally:
            chromium.close()

    async def _crawl(self, crawler, seeds, sink: CrawlSink, browser: BrowserSettings) -> None:
        run_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            wait_until="load",
            page_timeout=int(browser.navigation_timeout_s * 1000),
            check_robots_txt=False,  # applied by our CrawlPolicy, identically for both crawlers
            magic=False,
            simulate_user=False,
            override_navigator=False,
            remove_overlay_elements=False,
            remove_consent_popups=False,
            verbose=False,
        )
        captured: dict[str, object] = {}
        request_filter = RequestFilter(sink.policy, sink.blocked_navigations)

        async def on_context(page, context=None, **_kwargs):
            await request_filter.attach(page)
            return page

        async def before_return_html(page, html=None, context=None, config=None, **_kwargs):
            captured["capture"] = await capture_page(
                page,
                captured["url"],
                expand=browser.expand_interactive,
                javascript=browser.javascript,
            )
            return page

        crawler.crawler_strategy.set_hook("on_page_context_created", on_context)
        crawler.crawler_strategy.set_hook("before_return_html", before_return_html)

        frontier = deque(seeds)
        while frontier and not sink.should_stop():
            url = frontier.popleft()
            captured.clear()
            captured["url"] = url
            request_filter.navigating_to(url)
            await browser.pacer.wait_async()
            try:
                result = await crawler.arun(url, config=run_config)
            except Exception as exc:
                await sink.on_failure(url, f"{type(exc).__name__}: {exc}")
                continue
            capture = captured.get("capture")
            if capture is None:
                await sink.on_failure(url, (result.error_message or "page did not load")[:300])
                continue
            capture.status = result.status_code
            frontier.extend(await sink.on_page(capture))
