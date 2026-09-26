"""Crawler adapters. Each drives a browser its own way but hands every page to the same
capture_page() and CrawlSink, so their results are directly comparable (design §5.1)."""

from dataclasses import dataclass
from typing import Protocol

from brandguard.pipeline.crawl.policy import Pacer
from brandguard.pipeline.crawl.recorder import CrawlSink


@dataclass
class BrowserSettings:
    user_agent: str
    javascript: bool
    expand_interactive: bool
    pacer: Pacer
    executable_path: str | None = None
    navigation_timeout_s: float = 45.0


class CrawlerAdapter(Protocol):
    name: str

    def version(self) -> str: ...

    async def run(self, seeds: list[str], sink: CrawlSink, browser: BrowserSettings) -> None: ...


def get_adapter(name: str) -> CrawlerAdapter:
    if name == "crawlee":
        from brandguard.pipeline.crawl.adapters.crawlee_adapter import CrawleeAdapter

        return CrawleeAdapter()
    if name == "crawl4ai":
        from brandguard.pipeline.crawl.adapters.crawl4ai_adapter import Crawl4AIAdapter

        return Crawl4AIAdapter()
    raise ValueError(f"unknown crawler {name!r}")


CRAWLERS = ("crawlee", "crawl4ai")
