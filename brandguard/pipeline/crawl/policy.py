"""What the crawler may request, and how fast. Applied identically to both crawler adapters."""

import asyncio
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

from protego import Protego

from brandguard.core.http import ROBOTS_TOKEN


class SkipReason:
    NOT_HTTP = "not_http"
    SUBDOMAIN = "subdomain"  # another host of the same site, e.g. cdn.pfizer.com (D15)
    THIRD_PARTY = "third_party"  # another site entirely (D9)
    ROBOTS = "robots"
    NOT_INCLUDED = "not_included"  # doesn't match the include patterns
    EXCLUDED = "excluded"  # matches an exclude pattern


def normalize_url(url: str) -> str:
    """Drop the fragment, lower-case scheme and host, remove default ports."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    port = parts.port
    if port and not (
        (parts.scheme == "http" and port == 80) or (parts.scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    return urlunsplit((parts.scheme.lower(), host, parts.path or "/", parts.query, ""))


def _registrable(host: str) -> str:
    # Good enough to tell "another host of this site" from "another site" for reporting.
    labels = host.split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


@dataclass
class CrawlPolicy:
    allowed_domains: list[str]
    include_patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)
    robots: Protego | None = None  # None means robots.txt is not applied

    def __post_init__(self) -> None:
        self._domains = {d.lower() for d in self.allowed_domains}
        self._sites = {_registrable(d) for d in self._domains}
        self._include = [re.compile(p) for p in self.include_patterns]
        self._exclude = [re.compile(p) for p in self.exclude_patterns]

    def host_reason(self, url: str) -> str | None:
        """Why a URL's host is out of scope, or None if it is in scope."""
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            return SkipReason.NOT_HTTP
        host = (parts.hostname or "").lower()
        if host in self._domains:
            return None
        return SkipReason.SUBDOMAIN if _registrable(host) in self._sites else SkipReason.THIRD_PARTY

    def page_reason(self, url: str) -> str | None:
        """Why a page URL must not be crawled, or None if it may be."""
        reason = self.host_reason(url)
        if reason:
            return reason
        if self.robots is not None and not self.robots.can_fetch(url, ROBOTS_TOKEN):
            return SkipReason.ROBOTS
        if self._include and not any(p.search(url) for p in self._include):
            return SkipReason.NOT_INCLUDED
        if any(p.search(url) for p in self._exclude):
            return SkipReason.EXCLUDED
        return None


class Pacer:
    """Keeps at least `interval` seconds between the starts of consecutive requests.

    Shared by the sync discovery step and the async crawl, so the pace holds across both.
    It applies to page navigations and files the crawler fetches itself; resources a page
    loads while rendering (its CSS, scripts, images) load as in a normal browser.
    """

    def __init__(self, interval: float):
        self.interval = interval
        self._last: float | None = None

    def _delay(self) -> float:
        if self._last is None:
            return 0.0
        return max(0.0, self.interval - (time.monotonic() - self._last))

    def wait(self) -> None:
        delay = self._delay()
        if delay:
            time.sleep(delay)
        self._last = time.monotonic()

    async def wait_async(self) -> None:
        delay = self._delay()
        if delay:
            await asyncio.sleep(delay)
        self._last = time.monotonic()


BLOCK_STATUSES = frozenset({401, 403, 429, 503})
CHALLENGE_MARKERS = (
    "cf-chl",
    "challenge-platform",
    "px-captcha",
    "captcha",
    "pardon our interruption",
)


def looks_blocked(status: int | None, html: str) -> bool:
    """A refusal: a blocking status code, or a challenge page (sometimes served with 200)."""
    head = html[:200_000].lower()
    if status in BLOCK_STATUSES:
        return True
    return any(marker in head for marker in CHALLENGE_MARKERS[:3])
