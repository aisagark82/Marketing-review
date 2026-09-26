"""Run one crawl: robots.txt + sitemap discovery, then the chosen crawler adapter."""

import asyncio
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from brandguard.core import http
from brandguard.pipeline.crawl.adapters import BrowserSettings, get_adapter
from brandguard.pipeline.crawl.browser import chromium_executable
from brandguard.pipeline.crawl.discovery import discover
from brandguard.pipeline.crawl.policy import CrawlPolicy, Pacer
from brandguard.pipeline.crawl.recorder import CrawlSettings, CrawlSink
from brandguard.pipeline.files import process_images, process_pdfs


@dataclass
class CrawlConfig:
    run_id: int
    site_id: int
    crawler: str
    start_urls: list[str]
    allowed_domains: list[str]
    include_patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)
    max_pages: int = 500
    use_sitemap: bool = True
    respect_robots: bool = True
    request_interval_s: float = 2.0
    javascript: bool = True
    expand_interactive: bool = True
    stop_on_blocks: bool = True
    user_agent: str = ""
    data_dir: Path = Path(".")
    max_images: int = 100


class ResourceSampler:
    """Peak memory and CPU time of the worker process and its children (the browser)."""

    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self.peak_rss = 0
        self._child_cpu: dict[int, float] = {}
        self._stop = threading.Event()
        self._process = psutil.Process()
        self._cpu_start = sum(self._process.cpu_times()[:2])
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _sample(self) -> None:
        rss = self._process.memory_info().rss
        for child in self._process.children(recursive=True):
            try:
                rss += child.memory_info().rss
                self._child_cpu[child.pid] = sum(child.cpu_times()[:2])
            except psutil.Error:
                continue  # exited between listing and reading
        self.peak_rss = max(self.peak_rss, rss)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._sample()
            self._stop.wait(self.interval)

    def __enter__(self) -> "ResourceSampler":
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._stop.set()
        self._thread.join()

    def result(self) -> dict:
        own = sum(self._process.cpu_times()[:2]) - self._cpu_start
        return {
            "peak_rss_mb": round(self.peak_rss / 1_048_576),
            "cpu_s": round(own + sum(self._child_cpu.values()), 1),
        }


def execute_crawl(
    config: CrawlConfig, on_status=None, is_cancelled=None, read_image_text=None
) -> tuple[dict, str | None]:
    """Crawl a site's pages, then download and read its PDFs (and images, if read_image_text
    is given: a function (bytes, MIME type) -> lines of text).

    Returns (statistics, stop reason). Raises RobotsUnavailable.
    """
    adapter = get_adapter(config.crawler)
    pacer = Pacer(config.request_interval_s)
    policy = CrawlPolicy(config.allowed_domains, config.include_patterns, config.exclude_patterns)

    with http.make_http_client(config.user_agent) as client:
        found = discover(
            client,
            config.start_urls,
            policy,
            pacer,
            respect_robots=config.respect_robots,
            use_sitemap=config.use_sitemap,
            max_pages=config.max_pages,
        )
    if on_status:
        on_status(f"Crawling with {config.crawler}: {len(found.seeds)} pages to start from")

    sink = CrawlSink(
        CrawlSettings(
            config.run_id, config.site_id, config.max_pages, config.stop_on_blocks, config.data_dir
        ),
        policy,
        found.seeds,
    )
    browser = BrowserSettings(
        user_agent=config.user_agent,
        javascript=config.javascript,
        expand_interactive=config.expand_interactive,
        pacer=pacer,
        executable_path=chromium_executable(),
    )
    started = time.monotonic()
    with ResourceSampler() as sampler:
        asyncio.run(adapter.run(found.seeds, sink, browser))
        pages_runtime = time.monotonic() - started

        documents: dict = {}
        images: dict = {}
        if sink.stop_reason not in ("blocked", "cancelled"):
            if on_status:
                on_status("Downloading and reading PDFs")

            def progress(done: int, total: int) -> None:
                if on_status:
                    on_status(f"Reading PDFs: {done} of {total}")

            with http.make_http_client(config.user_agent) as client:
                documents = process_pdfs(
                    config.run_id,
                    client,
                    policy,
                    pacer,
                    config.data_dir,
                    should_stop=lambda: bool(is_cancelled and is_cancelled()),
                    on_progress=progress,
                )
                if read_image_text is not None and not (is_cancelled and is_cancelled()):
                    if on_status:
                        on_status("Reading text in images")

                    def image_progress(done: int, total: int) -> None:
                        if on_status:
                            on_status(f"Reading text in images: {done} of {total}")

                    images = process_images(
                        config.run_id,
                        client,
                        policy,
                        pacer,
                        config.data_dir,
                        read_image_text,
                        config.max_images,
                        should_stop=lambda: bool(is_cancelled and is_cancelled()),
                        on_progress=image_progress,
                    )
            if is_cancelled and is_cancelled():
                sink.stop_reason = "cancelled"

    stats = (
        sink.snapshot()
        | sampler.result()
        | {
            "documents": documents,
            "images": images,
            "pages_runtime_s": round(pages_runtime, 1),
            "crawler": config.crawler,
            "crawler_version": adapter.version(),
            "runtime_s": round(time.monotonic() - started, 1),
            "interval_s": pacer.interval,
            "crawl_delay_s": found.crawl_delay_s,
            "seeds": {
                "total": len(found.seeds),
                "from_sitemap": found.sitemap_urls,
                "sitemap_files_read": found.sitemap_files_read,
            },
            "notes": found.notes,
        }
    )
    return stats, sink.stop_reason
