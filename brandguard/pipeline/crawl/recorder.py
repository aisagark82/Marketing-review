"""Turns page captures into database rows and files, and decides what to crawl next.

`CrawlSink` is the one object both crawler adapters talk to, so scope, limits, block
handling and storage are identical whichever crawler runs.
"""

import asyncio
import gzip
import hashlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import insert

from brandguard.core.db import session_scope, utcnow
from brandguard.core.models import Asset, AssetKind, AssetStatus, Run, Segment
from brandguard.pipeline.crawl.capture import EXTRACTOR, PageCapture
from brandguard.pipeline.crawl.policy import CrawlPolicy, looks_blocked, normalize_url

CONSECUTIVE_BLOCKS_TO_STOP = 3
MAX_SKIPPED_ROWS = 5000  # skipped URLs beyond this are only counted
MAX_ERRORS_KEPT = 20


@dataclass
class CrawlSettings:
    run_id: int
    site_id: int
    max_pages: int
    stop_on_blocks: bool
    data_dir: Path


@dataclass
class CrawlCounters:
    pages: Counter = field(default_factory=Counter)  # ok / failed / blocked / redirected
    files: Counter = field(default_factory=Counter)  # in-scope files by kind
    skipped: Counter = field(default_factory=Counter)  # by reason
    segments: Counter = field(default_factory=Counter)  # by visibility
    sources: Counter = field(default_factory=Counter)  # by text source
    errors: list[str] = field(default_factory=list)


def store_file(data_dir: Path, folder: str, content: bytes, suffix: str) -> tuple[str, str]:
    """Content-addressed file under the data folder; short names keep Windows paths short."""
    digest = hashlib.sha256(content).hexdigest()
    relative = Path(folder) / digest[:2] / f"{digest}{suffix}"
    target = data_dir / relative
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return digest, relative.as_posix()


class CrawlSink:
    def __init__(self, settings: CrawlSettings, policy: CrawlPolicy, seeds: list[str]):
        self.settings = settings
        self.policy = policy
        self.counters = CrawlCounters()
        self.seen: set[str] = set(seeds)  # page URLs queued or crawled
        self.queued = len(seeds)
        self.recorded: dict[str, int] = {}  # URL -> asset id, for files and skipped URLs
        self.pages_done = 0
        self.consecutive_blocks = 0
        self.stop_reason: str | None = None
        # Filled by capture.install_routes: URL that tried to leave scope -> (target, reason)
        self.blocked_navigations: dict[str, tuple[str, str]] = {}

    # --- called by adapters -------------------------------------------------------------
    def should_stop(self) -> bool:
        return self.stop_reason is not None

    async def on_page(self, capture: PageCapture) -> list[str]:
        """Record a crawled page; returns the new in-scope page URLs to crawl."""
        return await asyncio.to_thread(self._on_page, capture)

    async def on_failure(self, url: str, error: str) -> None:
        await asyncio.to_thread(self._on_failure, url, error)

    # --- implementation (runs in a worker thread) ---------------------------------------
    def _check_cancel(self, session) -> None:
        run = session.get(Run, self.settings.run_id)
        if run.cancel_requested:
            self.stop_reason = "cancelled"

    def _progress(self, session, last_url: str) -> None:
        run = session.get(Run, self.settings.run_id)
        run.done = self.pages_done
        run.total = self.settings.max_pages
        files = sum(self.counters.files.values())
        run.message = f"{self.pages_done} pages, {files} files found · last: {last_url}"
        run.stats = self.snapshot()
        self._check_cancel(session)
        if self.pages_done >= self.settings.max_pages and not self.stop_reason:
            self.stop_reason = "page_limit"

    def _error(self, text: str) -> None:
        if len(self.counters.errors) < MAX_ERRORS_KEPT:
            self.counters.errors.append(text[:300])

    def _on_failure(self, url: str, error: str) -> None:
        self.pages_done += 1
        url = normalize_url(url)
        asset = Asset(
            run_id=self.settings.run_id,
            site_id=self.settings.site_id,
            url=url,
            kind=AssetKind.PAGE,
            fetched_at=utcnow(),
        )
        if url in self.blocked_navigations:
            # Not an error: the page redirects out of scope and the browser was stopped there.
            target, reason = self.blocked_navigations.pop(url)
            asset.status, asset.status_reason = AssetStatus.SKIPPED, f"redirected_{reason}"
            asset.final_url = target
            self.counters.pages["redirected_out_of_scope"] += 1
        else:
            asset.status, asset.status_reason = AssetStatus.FAILED, error[:200]
            self.counters.pages["failed"] += 1
            self._error(f"{url}: {error}")
        with session_scope() as session:
            session.add(asset)
            self._progress(session, url)

    def _on_page(self, capture: PageCapture) -> list[str]:
        self.pages_done += 1
        url = normalize_url(capture.requested_url)
        final_url = normalize_url(capture.final_url)
        self.seen.add(final_url)
        with session_scope() as session:
            asset = Asset(
                run_id=self.settings.run_id,
                site_id=self.settings.site_id,
                url=url,
                final_url=final_url if final_url != url else None,
                kind=AssetKind.PAGE,
                http_status=capture.status,
                fetched_at=utcnow(),
            )
            session.add(asset)
            new_links = self._classify_page(session, asset, capture)
            self._progress(session, url)
        return new_links

    def _classify_page(self, session, asset: Asset, capture: PageCapture) -> list[str]:
        walk = capture.walk or {}
        asset.title = walk.get("title")
        asset.language = walk.get("language")

        if looks_blocked(capture.status, capture.html):
            asset.status, asset.status_reason = AssetStatus.BLOCKED, f"HTTP {capture.status}"
            self.counters.pages["blocked"] += 1
            self.consecutive_blocks += 1
            if (
                self.settings.stop_on_blocks
                and self.consecutive_blocks >= CONSECUTIVE_BLOCKS_TO_STOP
            ):
                self.stop_reason = "blocked"
            return []
        self.consecutive_blocks = 0

        redirect_reason = self.policy.host_reason(capture.final_url)
        if redirect_reason:
            asset.status, asset.status_reason = AssetStatus.SKIPPED, f"redirected_{redirect_reason}"
            self.counters.pages["redirected_out_of_scope"] += 1
            return []
        if capture.status is not None and capture.status >= 400:
            asset.status, asset.status_reason = AssetStatus.FAILED, f"HTTP {capture.status}"
            self.counters.pages["failed"] += 1
            self._error(f"{asset.url}: HTTP {capture.status}")
            return []
        if capture.walk is None:
            asset.status, asset.status_reason = AssetStatus.FAILED, (capture.error or "")[:200]
            self.counters.pages["failed"] += 1
            self._error(f"{asset.url}: {capture.error}")
            return []

        asset.status = AssetStatus.OK
        if capture.html:
            asset.content_sha256, asset.html_path = store_file(
                self.settings.data_dir,
                "pages",
                gzip.compress(capture.html.encode("utf-8")),
                ".html.gz",
            )
        if capture.screenshot:
            _, asset.screenshot_path = store_file(
                self.settings.data_dir, "screenshots", capture.screenshot, ".jpg"
            )
        session.flush()  # asset.id for the rows below

        segments = walk.get("segments", [])
        if segments:
            session.execute(
                insert(Segment),
                [
                    {
                        "asset_id": asset.id,
                        "text": s["text"],
                        "text_source": s["source"],
                        "visibility": s["visibility"],
                        "render_transform": s.get("transform"),
                        "locator": s.get("locator"),
                        "extractor": EXTRACTOR,
                    }
                    for s in segments
                ],
            )
        by_visibility = Counter(s["visibility"] for s in segments)
        self.counters.segments.update(by_visibility)
        self.counters.sources.update(s["source"] for s in segments)
        self.counters.pages["ok"] += 1
        asset.info = {
            "size": walk.get("size"),
            "segments": dict(by_visibility),
            "segments_truncated": walk.get("truncated", False),
            "expanded": capture.expanded,
            "timings": capture.timings,
        }

        links = list(walk.get("links", []))
        for resource in walk.get("resources", []):
            if resource["kind"] == AssetKind.FRAME and not self.policy.host_reason(resource["url"]):
                links.append({"url": resource["url"]})  # a frame on this site is just another page
            else:
                self._record_resource(session, asset, resource)
        return self._new_links(session, asset, links)

    def _record_resource(self, session, page: Asset, resource: dict) -> None:
        url = normalize_url(resource["url"])
        if url in self.recorded:
            return
        kind = resource["kind"] if resource["kind"] in vars(AssetKind).values() else AssetKind.OTHER
        reason = self.policy.host_reason(url)
        if reason:
            self.counters.skipped[reason] += 1
            status = AssetStatus.SKIPPED
        else:
            self.counters.files[kind] += 1
            status = AssetStatus.DISCOVERED
        if status == AssetStatus.SKIPPED and len(self.recorded) >= MAX_SKIPPED_ROWS:
            return
        row = Asset(
            run_id=self.settings.run_id,
            site_id=self.settings.site_id,
            url=url,
            kind=kind,
            status=status,
            status_reason=reason,
            found_on_id=page.id,
            info={"tag": resource.get("tag"), "visible": resource.get("visible")},
        )
        session.add(row)
        session.flush()
        self.recorded[url] = row.id

    def _new_links(self, session, page: Asset, links: list[dict]) -> list[str]:
        fresh: list[str] = []
        for link in links:
            url = normalize_url(link["url"])
            if url in self.seen or url in self.recorded:
                continue
            reason = self.policy.page_reason(url)
            if reason:
                self.counters.skipped[reason] += 1
                if len(self.recorded) < MAX_SKIPPED_ROWS:
                    row = Asset(
                        run_id=self.settings.run_id,
                        site_id=self.settings.site_id,
                        url=url,
                        kind=AssetKind.PAGE,
                        status=AssetStatus.SKIPPED,
                        status_reason=reason,
                        found_on_id=page.id,
                    )
                    session.add(row)
                    session.flush()
                    self.recorded[url] = row.id
                continue
            self.seen.add(url)
            if self.queued >= self.settings.max_pages:
                self.counters.skipped["page_limit"] += 1
                continue
            self.queued += 1
            fresh.append(url)
        return fresh

    def snapshot(self) -> dict:
        c = self.counters
        return {
            "pages": dict(c.pages),
            "files": dict(c.files),
            "skipped": dict(c.skipped),
            "segments": dict(c.segments),
            "sources": dict(c.sources.most_common()),
            "errors": list(c.errors),
            "stopped": self.stop_reason,
        }
