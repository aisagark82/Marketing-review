"""Before the browser starts: read robots.txt fresh and collect seed URLs from the sitemap."""

from dataclasses import dataclass, field

import httpx
from protego import Protego

from brandguard.core.http import ROBOTS_TOKEN, fetch
from brandguard.pipeline.crawl.policy import CrawlPolicy, Pacer, normalize_url
from brandguard.pipeline.preflight import MAX_ROBOTS_BYTES, MAX_SITEMAP_BYTES, parse_sitemap

MAX_SITEMAP_FILES = 50


class RobotsUnavailable(Exception):
    """robots.txt couldn't be read, which counts as "disallow everything" (RFC 9309, D21)."""


@dataclass
class Discovery:
    robots: Protego | None
    crawl_delay_s: float | None
    seeds: list[str]
    sitemap_urls: int = 0
    sitemap_files_read: int = 0
    notes: list[str] = field(default_factory=list)


def read_robots(
    client: httpx.Client, start_url: str, pacer: Pacer
) -> tuple[Protego | None, list[str]]:
    origin = start_url.split("/", 3)
    robots_url = f"{origin[0]}//{origin[2]}/robots.txt"
    pacer.wait()
    fetched = fetch(client, robots_url, MAX_ROBOTS_BYTES)
    if fetched.error or (fetched.status_code or 0) >= 500 or fetched.status_code in (401, 403):
        raise RobotsUnavailable(fetched.error or f"HTTP {fetched.status_code}")
    if not fetched.ok:
        return None, []  # no robots.txt: no restrictions
    parser = Protego.parse(fetched.text())
    return parser, list(parser.sitemaps)


def discover(
    client: httpx.Client,
    start_urls: list[str],
    policy: CrawlPolicy,
    pacer: Pacer,
    *,
    respect_robots: bool,
    use_sitemap: bool,
    max_pages: int,
) -> Discovery:
    robots, sitemaps = read_robots(client, start_urls[0], pacer)
    if respect_robots:
        policy.robots = robots
    delay = robots.crawl_delay(ROBOTS_TOKEN) if robots else None
    if delay:
        pacer.interval = max(pacer.interval, delay)

    seeds: list[str] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        normalized = normalize_url(url)
        if normalized not in seen and len(seeds) < max_pages and not policy.page_reason(normalized):
            seen.add(normalized)
            seeds.append(normalized)

    for url in start_urls:
        add(url)
    result = Discovery(robots=robots, crawl_delay_s=delay, seeds=seeds)
    if not use_sitemap:
        return result

    first = start_urls[0].split("/", 3)
    queue = sitemaps or [f"{first[0]}//{first[2]}/sitemap.xml"]
    opened: set[str] = set()
    while queue and len(seeds) < max_pages and result.sitemap_files_read < MAX_SITEMAP_FILES:
        url = queue.pop(0)
        if url in opened or (policy.robots and not policy.robots.can_fetch(url, ROBOTS_TOKEN)):
            continue
        opened.add(url)
        pacer.wait()
        fetched = fetch(client, url, MAX_SITEMAP_BYTES)
        result.sitemap_files_read += 1
        if not fetched.ok:
            result.notes.append(f"sitemap {url}: {fetched.error or f'HTTP {fetched.status_code}'}")
            continue
        try:
            kind, locs = parse_sitemap(fetched.body)
        except Exception as exc:
            result.notes.append(f"sitemap {url}: could not parse ({exc})")
            continue
        if kind == "sitemapindex":
            queue.extend(locs)
            continue
        before = len(seeds)
        for loc in locs:
            add(loc)
        result.sitemap_urls += len(seeds) - before
    return result
