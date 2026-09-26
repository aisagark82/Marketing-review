"""Crawlee for Python (Apache-2.0) driving Playwright Chromium.

Crawlee defaults changed here, all for the independent-test policy (design §8.1):
- fingerprint_generator=None: Crawlee spoofs browser fingerprints by default
- extra_http_headers={}: even without fingerprints, Crawlee's default header generator adds a
  made-up User-Agent and sec-ch-ua headers to every request; an explicit value turns it off
- use_session_pool=False, retry_on_blocked=False, max_request_retries=0: no rotating
  identities, no retrying refusals or failures (each URL is requested once)
- respect_robots_txt_file=False: robots.txt is applied by our CrawlPolicy, identically for
  both crawlers
- HTTP error pages reach our handler (so 403/429 are recorded and counted, not retried)
- a request queue of its own per crawl, dropped afterwards: Crawlee's default queue lives on in
  the process, so URLs left over from a stopped crawl would be requested by the next crawl
"""

import importlib.metadata
import uuid
from datetime import timedelta

from crawlee import ConcurrencySettings
from crawlee.configuration import Configuration
from crawlee.crawlers import (
    PlaywrightCrawler,
    PlaywrightCrawlingContext,
    PlaywrightPreNavCrawlingContext,
)
from crawlee.storage_clients import MemoryStorageClient
from crawlee.storages import RequestQueue

from brandguard.pipeline.crawl.adapters import BrowserSettings
from brandguard.pipeline.crawl.browser import running_as_root
from brandguard.pipeline.crawl.capture import VIEWPORT, RequestFilter, capture_page
from brandguard.pipeline.crawl.recorder import CrawlSink


class _Stopped(Exception):
    """Raised before navigating once the crawl has to stop, so no further page is requested."""


class CrawleeAdapter:
    name = "crawlee"

    def version(self) -> str:
        return importlib.metadata.version("crawlee")

    async def run(self, seeds: list[str], sink: CrawlSink, browser: BrowserSettings) -> None:
        storage = MemoryStorageClient()
        queue = await RequestQueue.open(
            alias=f"brandguard-run-{sink.settings.run_id}-{uuid.uuid4().hex}",
            storage_client=storage,
        )
        try:
            await self._crawl(seeds, sink, browser, storage, queue)
        finally:
            await queue.drop()

    async def _crawl(self, seeds, sink: CrawlSink, browser: BrowserSettings, storage, queue):
        launch: dict = (
            {"executable_path": browser.executable_path} if browser.executable_path else {}
        )
        if running_as_root():
            launch["chromium_sandbox"] = False
        crawler = PlaywrightCrawler(
            browser_type="chromium",
            headless=True,
            browser_launch_options=launch,
            browser_new_context_options={
                "user_agent": browser.user_agent,
                "extra_http_headers": {},
                "java_script_enabled": browser.javascript,
                "viewport": VIEWPORT,
            },
            fingerprint_generator=None,
            navigation_timeout=timedelta(seconds=browser.navigation_timeout_s),
            configuration=Configuration(purge_on_start=True),
            storage_client=storage,
            request_manager=queue,
            configure_logging=False,
            use_session_pool=False,
            retry_on_blocked=False,
            respect_robots_txt_file=False,
            max_request_retries=0,  # as in the Crawl4AI adapter: record failures, don't retry
            max_requests_per_crawl=sink.settings.max_pages,
            ignore_http_error_status_codes=list(range(400, 600)),
            concurrency_settings=ConcurrencySettings(
                min_concurrency=1, max_concurrency=1, desired_concurrency=1
            ),
            request_handler_timeout=timedelta(minutes=3),
        )
        request_filter = RequestFilter(sink.policy, sink.blocked_navigations)

        @crawler.pre_navigation_hook
        async def before_navigation(context: PlaywrightPreNavCrawlingContext) -> None:
            if sink.should_stop():
                crawler.stop(f"stopped: {sink.stop_reason}")
                context.request.no_retry = True
                raise _Stopped
            await request_filter.attach(context.page)
            request_filter.navigating_to(context.request.url)
            await browser.pacer.wait_async()

        @crawler.router.default_handler
        async def handle(context: PlaywrightCrawlingContext) -> None:
            if sink.should_stop():
                crawler.stop(f"stopped: {sink.stop_reason}")
                return
            capture = await capture_page(
                context.page,
                context.request.url,
                expand=browser.expand_interactive,
                javascript=browser.javascript,
            )
            capture.status = context.response.status if context.response else None
            links = await sink.on_page(capture)
            if sink.should_stop():
                crawler.stop(f"stopped: {sink.stop_reason}")
            elif links:
                await context.add_requests(links)

        @crawler.failed_request_handler
        async def failed(context, error: Exception) -> None:
            if isinstance(error, _Stopped) or sink.should_stop():
                return  # never requested: the crawl was stopping
            await sink.on_failure(context.request.url, f"{type(error).__name__}: {error}")

        await crawler.run(seeds)
