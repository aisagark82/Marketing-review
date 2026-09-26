"""Pre-flight check before crawling a site (design §8.1).

Makes a handful of polite requests (robots.txt, the first start page, up to a few
sitemap files) and reports whether crawling is allowed and what the crawler should
respect. It never downloads more than it needs to show the user.
"""

import gzip
import io
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx
from defusedxml import ElementTree
from protego import Protego

from brandguard.core.db import utcnow
from brandguard.core.http import ROBOTS_TOKEN, Fetched, fetch

MAX_ROBOTS_BYTES = 512_000
MAX_PAGE_BYTES = 5_000_000
MAX_SITEMAP_BYTES = 10_000_000
MAX_SITEMAP_DECOMPRESSED_BYTES = 50_000_000
MAX_SITEMAP_FETCHES = 3
SAMPLE_URLS = 10
MAX_TERMS_LINKS = 5
ROBOTS_DISPLAY_CHARS = 20_000

STEPS = ("robots.txt", "start page", "sitemap", "terms of use")

# Link text or URL that usually points to terms of use / legal notices, in the design's languages.
TERMS_PATTERN = re.compile(
    r"terms|legal|conditions|disclaimer|nutzungsbedingungen|impressum|condiciones|"
    r"aviso legal|利用規約|ご利用条件|使用条款|法律声明|使用條款",
    re.IGNORECASE,
)
BOT_PROTECTION_MARKERS = (
    "captcha",
    "challenge-platform",
    "cf-chl",
    "access denied",
    "pardon our interruption",
    "are you a robot",
    "request unsuccessful. incapsula",
    "perimeterx",
    "px-captcha",
)
BLOCKING_STATUSES = frozenset({401, 403, 429, 503})

CheckStatus = Literal["ok", "info", "warn", "fail"]
ProgressFn = Callable[[str, int, int], None]


@dataclass
class PreflightConfig:
    start_urls: list[str]
    allowed_domains: list[str]
    use_sitemap: bool
    respect_robots: bool
    request_interval_s: float
    user_agent: str


@dataclass
class Check:
    id: str
    label: str
    status: CheckStatus
    detail: str


@dataclass
class RobotsReport:
    url: str
    status_code: int | None
    found: bool
    crawl_delay_s: float | None = None
    sitemaps: list[str] = field(default_factory=list)
    groups: list[dict] = field(default_factory=list)
    start_urls_allowed: dict[str, bool] = field(default_factory=dict)
    raw: str = ""
    error: str | None = None


@dataclass
class PageReport:
    url: str
    final_url: str
    status_code: int | None
    redirects: list[str]
    in_scope: bool
    title: str | None = None
    in_scope_links: int = 0
    bot_protection: str | None = None
    error: str | None = None


@dataclass
class SitemapReport:
    checked: list[dict] = field(default_factory=list)
    urls_seen: int = 0
    in_scope_urls: int = 0
    unchecked_sitemaps: int = 0
    sample_urls: list[str] = field(default_factory=list)


def host_in_scope(url: str, allowed_domains: list[str]) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host in {d.lower() for d in allowed_domains}


class _Pacer:
    """Keeps at least `interval` seconds between the start of consecutive requests."""

    def __init__(self, interval: float, sleep: Callable[[float], None]):
        self.interval = interval
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            remaining = self.interval - (time.monotonic() - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = time.monotonic()


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.title: str | None = None
        self._in_title = False
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "title" and self.title is None:
            self._in_title = True
        elif tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or "") + data
        if self._href is not None:
            self._text.append(data)


def relevant_robots_groups(text: str, token: str = ROBOTS_TOKEN) -> list[dict]:
    """The robots.txt groups this crawler must obey: its own token's groups, else `*` (RFC 9309)."""
    groups: list[dict] = []
    current: dict | None = None
    previous_was_agent = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        name, value = (part.strip() for part in line.split(":", 1))
        name = name.lower()
        if name == "user-agent":
            if current is None or not previous_was_agent:
                current = {"user_agents": [], "rules": []}
                groups.append(current)
            current["user_agents"].append(value)
            previous_was_agent = True
            continue
        previous_was_agent = False
        if current is not None and name in ("allow", "disallow", "crawl-delay"):
            current["rules"].append([name.title(), value])

    def matches(group: dict, wanted: str) -> bool:
        return any(agent.lower() == wanted for agent in group["user_agents"])

    own = [g for g in groups if matches(g, token.lower())]
    return own or [g for g in groups if matches(g, "*")]


def detect_bot_protection(page: Fetched) -> str | None:
    if page.status_code not in BLOCKING_STATUSES:
        return None
    headers = page.headers
    if "cf-mitigated" in headers:
        return "Cloudflare challenge (cf-mitigated header)"
    body = page.body[:200_000].decode("utf-8", errors="ignore").lower()
    for marker in BOT_PROTECTION_MARKERS:
        if marker in body:
            return f'Bot-protection page (contains "{marker}")'
    server = headers.get("server", "").lower()
    for vendor in ("cloudflare", "akamai", "incapsula", "imperva"):
        if vendor in server:
            return f"Blocked by {vendor.title()} (HTTP {page.status_code})"
    return None


def _check_robots(
    client: httpx.Client, config: PreflightConfig, pacer: _Pacer
) -> tuple[RobotsReport, Protego | None, list[Check]]:
    first = urlsplit(config.start_urls[0])
    robots_url = f"{first.scheme}://{first.netloc}/robots.txt"
    pacer.wait()
    fetched = fetch(client, robots_url, MAX_ROBOTS_BYTES)
    report = RobotsReport(url=robots_url, status_code=fetched.status_code, found=fetched.ok)
    checks: list[Check] = []

    if fetched.error or (fetched.status_code or 0) >= 500:
        # RFC 9309: an unreachable robots.txt means the crawler must assume full disallow.
        report.error = fetched.error or f"HTTP {fetched.status_code}"
        checks.append(
            Check(
                "robots",
                "robots.txt",
                "fail",
                f"robots.txt could not be read ({report.error}), so crawling is treated as "
                "not allowed. Try again later.",
            )
        )
        return report, None, checks
    if fetched.status_code in (401, 403):
        # Stricter than RFC 9309 on purpose: for an independent test a blocked
        # robots.txt is read as "no".
        report.error = f"HTTP {fetched.status_code}"
        checks.append(
            Check(
                "robots",
                "robots.txt",
                "fail",
                f"robots.txt returned HTTP {fetched.status_code}. For an independent test this is "
                "treated as not allowed.",
            )
        )
        return report, None, checks

    text = fetched.text() if fetched.ok else ""
    parser = Protego.parse(text)
    report.raw = text[:ROBOTS_DISPLAY_CHARS]
    report.crawl_delay_s = parser.crawl_delay(ROBOTS_TOKEN)
    report.sitemaps = list(parser.sitemaps)
    report.groups = relevant_robots_groups(text)
    report.start_urls_allowed = {u: parser.can_fetch(u, ROBOTS_TOKEN) for u in config.start_urls}

    if fetched.ok:
        detail = f"Found ({len(report.groups)} group(s) apply to BrandGuard)."
    else:
        detail = f"No robots.txt (HTTP {fetched.status_code}); the site sets no crawl restrictions."
    checks.append(Check("robots", "robots.txt", "ok" if fetched.ok else "info", detail))

    blocked = [u for u, allowed in report.start_urls_allowed.items() if not allowed]
    if blocked and config.respect_robots:
        checks.append(
            Check(
                "robots-start",
                "Start URLs allowed",
                "fail",
                "robots.txt disallows: " + ", ".join(blocked),
            )
        )
    elif blocked:
        checks.append(
            Check(
                "robots-start",
                "Start URLs allowed",
                "warn",
                "robots.txt disallows these, but respecting robots.txt is switched off: "
                + ", ".join(blocked),
            )
        )
    else:
        checks.append(
            Check("robots-start", "Start URLs allowed", "ok", "robots.txt allows every start URL.")
        )
    return report, parser, checks


def _check_start_page(
    client: httpx.Client,
    config: PreflightConfig,
    pacer: _Pacer,
    robots: Protego | None,
) -> tuple[PageReport | None, list[tuple[str, str]], list[Check]]:
    url = config.start_urls[0]
    if config.respect_robots and robots is not None and not robots.can_fetch(url, ROBOTS_TOKEN):
        return (
            None,
            [],
            [Check("start-page", "Start page", "fail", "Not fetched: robots.txt disallows it.")],
        )

    pacer.wait()
    page = fetch(client, url, MAX_PAGE_BYTES)
    report = PageReport(
        url=url,
        final_url=page.final_url,
        status_code=page.status_code,
        redirects=page.redirects,
        in_scope=host_in_scope(page.final_url, config.allowed_domains),
        error=page.error,
    )
    if page.error:
        return (
            report,
            [],
            [Check("start-page", "Start page", "fail", f"Could not load {url}: {page.error}")],
        )

    report.bot_protection = detect_bot_protection(page)
    if report.bot_protection:
        return (
            report,
            [],
            [
                Check(
                    "start-page",
                    "Start page",
                    "fail",
                    f"{report.bot_protection}. The crawler does not try to get "
                    "around bot protection, so this site can't be crawled.",
                )
            ],
        )
    if not page.ok:
        return (
            report,
            [],
            [Check("start-page", "Start page", "fail", f"{url} returned HTTP {page.status_code}.")],
        )
    if not report.in_scope:
        return (
            report,
            [],
            [
                Check(
                    "start-page",
                    "Start page",
                    "fail",
                    f"{url} redirects to {page.final_url}, which is outside the allowed domains.",
                )
            ],
        )

    parser = _LinkParser()
    parser.feed(page.text())
    report.title = " ".join((parser.title or "").split()) or None
    links = [(urljoin(page.final_url, href), text) for href, text in parser.links]
    report.in_scope_links = len(
        {u.split("#")[0] for u, _ in links if host_in_scope(u, config.allowed_domains)}
    )
    detail = f"HTTP {page.status_code}, {report.in_scope_links} in-scope links"
    if page.redirects:
        detail += f" (redirected to {page.final_url})"
    return report, links, [Check("start-page", "Start page", "ok", detail + ".")]


def parse_sitemap(body: bytes) -> tuple[str, list[str]]:
    if body[:2] == b"\x1f\x8b":
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as archive:
            body = archive.read(MAX_SITEMAP_DECOMPRESSED_BYTES + 1)
        if len(body) > MAX_SITEMAP_DECOMPRESSED_BYTES:
            raise ValueError("sitemap is too large when decompressed")
    root = ElementTree.fromstring(body)
    kind = root.tag.rsplit("}", 1)[-1]
    locs = [el.text.strip() for el in root.iter() if el.tag.endswith("loc") and el.text]
    return kind, locs


def _check_sitemaps(
    client: httpx.Client,
    config: PreflightConfig,
    pacer: _Pacer,
    robots: Protego | None,
    robots_report: RobotsReport,
) -> tuple[SitemapReport, list[Check]]:
    report = SitemapReport()
    if not config.use_sitemap:
        return report, [Check("sitemap", "Sitemap", "info", "Sitemap use is switched off.")]

    first = urlsplit(config.start_urls[0])
    queue = list(robots_report.sitemaps) or [f"{first.scheme}://{first.netloc}/sitemap.xml"]
    seen: set[str] = set()
    fetches = 0
    while queue and fetches < MAX_SITEMAP_FETCHES:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        if config.respect_robots and robots is not None and not robots.can_fetch(url, ROBOTS_TOKEN):
            report.checked.append(
                {"url": url, "status_code": None, "error": "disallowed by robots.txt"}
            )
            continue
        pacer.wait()
        fetches += 1
        fetched = fetch(client, url, MAX_SITEMAP_BYTES)
        entry: dict = {"url": url, "status_code": fetched.status_code}
        report.checked.append(entry)
        if not fetched.ok:
            entry["error"] = fetched.error or f"HTTP {fetched.status_code}"
            continue
        try:
            kind, locs = parse_sitemap(fetched.body)
        except Exception as exc:  # malformed, oversized or hostile XML
            entry["error"] = f"could not parse: {exc}"
            continue
        entry.update(type=kind, entries=len(locs))
        if kind == "sitemapindex":
            queue.extend(locs)
        else:
            in_scope = [u for u in locs if host_in_scope(u, config.allowed_domains)]
            report.urls_seen += len(locs)
            report.in_scope_urls += len(in_scope)
            room = SAMPLE_URLS - len(report.sample_urls)
            report.sample_urls.extend(in_scope[:room])
    report.unchecked_sitemaps = len([u for u in queue if u not in seen])

    if report.urls_seen:
        detail = f"{report.in_scope_urls} in-scope page URLs in the sampled sitemap files"
        if report.unchecked_sitemaps:
            detail += (
                f"; {report.unchecked_sitemaps} more sitemap file(s) not opened now "
                "(the crawl reads them)"
            )
        return report, [Check("sitemap", "Sitemap", "ok", detail + ".")]
    return report, [
        Check(
            "sitemap",
            "Sitemap",
            "warn",
            "No usable sitemap found; the crawler will discover pages by following links instead.",
        )
    ]


def _check_terms(links: list[tuple[str, str]], page: PageReport | None) -> tuple[list[dict], Check]:
    found: list[dict] = []
    for url, text in links:
        if len(found) >= MAX_TERMS_LINKS:
            break
        looks_like_terms = TERMS_PATTERN.search(text) or TERMS_PATTERN.search(url)
        is_new = all(existing["url"] != url for existing in found)
        if looks_like_terms and url.startswith("http") and is_new:
            found.append({"text": text or url, "url": url})
    if found:
        return found, Check(
            "terms", "Terms of use", "info", "Review the linked terms before acknowledging."
        )
    page_read = page is not None and page.status_code is not None and 200 <= page.status_code < 300
    reason = "no link found" if page_read else "the start page could not be read"
    return found, Check(
        "terms",
        "Terms of use",
        "warn",
        f"Find and review the site's terms of use yourself ({reason}).",
    )


def run_preflight(
    config: PreflightConfig,
    client: httpx.Client,
    progress: ProgressFn | None = None,
    sleep: Callable[[float], None] | None = None,
) -> dict:
    """Run every check and return a JSON-serializable result."""
    sleep = sleep or time.sleep

    def step(index: int) -> None:
        if progress:
            progress(STEPS[index], index, len(STEPS))

    # robots.txt comes first because its Crawl-delay governs the requests after it.
    pacer = _Pacer(config.request_interval_s, sleep)
    step(0)
    robots_report, robots, checks = _check_robots(client, config, pacer)
    effective_interval = max(config.request_interval_s, robots_report.crawl_delay_s or 0)
    pacer.interval = effective_interval
    if robots_report.crawl_delay_s:
        checks.append(
            Check(
                "crawl-delay",
                "Request pace",
                "info",
                f"robots.txt asks for {robots_report.crawl_delay_s:g} s between requests; "
                f"the crawler will wait {effective_interval:g} s.",
            )
        )
    else:
        checks.append(
            Check(
                "crawl-delay",
                "Request pace",
                "info",
                f"The crawler will wait {effective_interval:g} s between requests.",
            )
        )

    page_report: PageReport | None = None
    links: list[tuple[str, str]] = []
    sitemap_report = SitemapReport()
    # No parser means robots.txt couldn't be read, which counts as "disallow everything".
    if robots is not None:
        step(1)
        page_report, links, page_checks = _check_start_page(client, config, pacer, robots)
        checks += page_checks
        step(2)
        if page_report is not None and page_report.bot_protection:
            # The site is actively refusing automated requests: stop asking.
            checks.append(
                Check(
                    "sitemap",
                    "Sitemap",
                    "info",
                    "Skipped: the site is blocking automated requests.",
                )
            )
        else:
            sitemap_report, sitemap_checks = _check_sitemaps(
                client, config, pacer, robots, robots_report
            )
            checks += sitemap_checks
    step(3)
    terms_links, terms_check = _check_terms(links, page_report)
    checks.append(terms_check)

    can_crawl = all(c.status != "fail" for c in checks)
    failed = [f"{c.label}: {c.detail}" for c in checks if c.status == "fail"]
    summary = (
        "No blockers found. Review robots.txt and the terms of use, then acknowledge."
        if can_crawl
        else "Crawling is not possible. " + " ".join(failed)
    )
    if progress:
        progress("done", len(STEPS), len(STEPS))
    return {
        "checked_at": utcnow().isoformat(),
        "user_agent": config.user_agent,
        "can_crawl": can_crawl,
        "summary": summary,
        "effective_interval_s": effective_interval,
        "checks": [asdict(c) for c in checks],
        "robots": asdict(robots_report),
        "start_page": asdict(page_report) if page_report else None,
        "sitemap": asdict(sitemap_report),
        "terms_links": terms_links,
    }
