"""Capture one rendered page: text segments (via walker.js), links, files, HTML and screenshot.

Shared by both crawler adapters so the comparison measures the crawlers, not the extraction.
"""

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path

SCRIPTS = Path(__file__).parent
WALKER_JS = (SCRIPTS / "walker.js").read_text(encoding="utf-8")
SCROLL_JS = (SCRIPTS / "scroll.js").read_text(encoding="utf-8")
EXPAND_JS = (SCRIPTS / "expand.js").read_text(encoding="utf-8")
EXTRACTOR = "dom-walker/1"

VIEWPORT = {"width": 1366, "height": 900}
MAX_SCREENSHOT_HEIGHT = 20_000


@dataclass
class PageCapture:
    requested_url: str
    final_url: str
    status: int | None = None
    html: str = ""
    walk: dict | None = None
    screenshot: bytes | None = None
    expanded: int = 0
    error: str | None = None
    timings: dict[str, float] = field(default_factory=dict)


async def capture_page(page, requested_url: str, *, expand: bool, javascript: bool) -> PageCapture:
    """Everything BrandGuard needs from a loaded page. Errors are recorded, not raised."""
    capture = PageCapture(requested_url=requested_url, final_url=page.url)
    started = time.perf_counter()

    def lap(name: str) -> None:
        capture.timings[name] = round(time.perf_counter() - started, 3)

    try:
        if javascript:
            await page.evaluate(SCROLL_JS)
            if expand:
                capture.expanded = await page.evaluate(EXPAND_JS)
            lap("prepare")
        capture.walk = await page.evaluate(WALKER_JS)
        lap("walk")
    except Exception as exc:  # page navigated away, crashed or scripts are disabled
        capture.error = f"text extraction failed: {type(exc).__name__}: {exc}"

    try:
        capture.html = await page.content()
    except Exception as exc:
        capture.error = capture.error or f"could not read HTML: {exc}"

    try:
        height = (capture.walk or {}).get("size", [0, 0])[1]
        options = {"type": "jpeg", "quality": 60, "full_page": True, "timeout": 30_000}
        if height > MAX_SCREENSHOT_HEIGHT:
            options["clip"] = {
                "x": 0,
                "y": 0,
                "width": VIEWPORT["width"],
                "height": MAX_SCREENSHOT_HEIGHT,
            }
        capture.screenshot = await page.screenshot(**options)
        lap("screenshot")
    except Exception:
        capture.screenshot = None  # evidence is optional; text is what matters

    capture.final_url = page.url
    return capture


class RequestFilter:
    """Per-page request filter over the Chrome DevTools Protocol, used by both adapters.

    - audio/video are not downloaded while rendering (media files are handled separately)
    - page loads (the page itself, its redirects and its iframes) to out-of-scope hosts are
      aborted, so the browser never loads a third-party or other-subdomain page. When the page
      being crawled redirects away, where it was heading is recorded.
    Everything else a page loads (its CSS, scripts, images) loads as in a normal browser.

    CDP rather than Playwright's page.route(): route() doesn't see redirect hops, and
    fulfilling the page ourselves to catch them makes Chromium drop the page's images.
    """

    def __init__(self, policy, blocked_navigations: dict[str, tuple[str, str]]):
        self.policy = policy
        self.blocked_navigations = blocked_navigations
        self.current_url: str | None = None  # the page being crawled (one at a time)
        self._attached: set[int] = set()

    async def attach(self, page) -> None:
        if id(page) in self._attached:
            return
        self._attached.add(id(page))
        cdp = await page.context.new_cdp_session(page)
        tree = await cdp.send("Page.getFrameTree")
        main_frame = tree["frameTree"]["frame"]["id"]

        async def on_paused(event: dict) -> None:
            request_id = event["requestId"]
            url = event["request"]["url"]
            try:
                if event["resourceType"] == "Media":
                    await cdp.send(
                        "Fetch.failRequest",
                        {"requestId": request_id, "errorReason": "BlockedByClient"},
                    )
                    return
                reason = self.policy.host_reason(url)
                if reason:
                    if event.get("frameId") == main_frame and self.current_url:
                        self.blocked_navigations[self.current_url] = (url, reason)
                    await cdp.send(
                        "Fetch.failRequest",
                        {"requestId": request_id, "errorReason": "BlockedByClient"},
                    )
                    return
                await cdp.send("Fetch.continueRequest", {"requestId": request_id})
            except Exception:
                pass  # the page closed while the request was paused

        cdp.on("Fetch.requestPaused", lambda event: asyncio.ensure_future(on_paused(event)))
        await cdp.send(
            "Fetch.enable", {"patterns": [{"resourceType": "Document"}, {"resourceType": "Media"}]}
        )

    def navigating_to(self, url: str) -> None:
        from brandguard.pipeline.crawl.policy import normalize_url

        self.current_url = normalize_url(url)
