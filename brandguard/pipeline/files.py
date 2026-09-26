"""Download and extract the files a crawl found. Phase 0: PDFs (other kinds stay "discovered").

Same politeness as pages: robots.txt, the crawl's pace, honest User-Agent, and a stop after
repeated refusals.
"""

from collections import Counter
from collections.abc import Callable
from pathlib import Path

import httpx
from sqlalchemy import insert, select

from brandguard.core.db import session_scope, utcnow
from brandguard.core.http import ROBOTS_TOKEN, fetch
from brandguard.core.models import Asset, AssetKind, AssetStatus, Segment
from brandguard.pipeline.crawl.policy import BLOCK_STATUSES, CrawlPolicy, Pacer
from brandguard.pipeline.crawl.recorder import CONSECUTIVE_BLOCKS_TO_STOP, store_file
from brandguard.pipeline.extract.pdf import EXTRACTOR, PdfError, extract_pdf

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_FILES_PER_RUN = 200


def _finish(asset_id: int, **fields) -> None:
    with session_scope() as session:
        asset = session.get(Asset, asset_id)
        asset.fetched_at = utcnow()
        for name, value in fields.items():
            setattr(asset, name, value)


def process_pdfs(
    run_id: int,
    client: httpx.Client,
    policy: CrawlPolicy,
    pacer: Pacer,
    data_dir: Path,
    should_stop: Callable[[], bool],
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
    with session_scope() as session:
        pending = session.execute(
            select(Asset.id, Asset.url)
            .where(
                Asset.run_id == run_id,
                Asset.kind == AssetKind.PDF,
                Asset.status == AssetStatus.DISCOVERED,
            )
            .order_by(Asset.id)
        ).all()

    stats: Counter = Counter()
    consecutive_blocks = 0
    for index, (asset_id, url) in enumerate(pending):
        if index >= MAX_FILES_PER_RUN:
            stats["over_file_limit"] = len(pending) - index
            break
        if should_stop():
            stats["not_processed"] = len(pending) - index
            break
        if on_progress:
            on_progress(index, len(pending))
        if policy.robots is not None and not policy.robots.can_fetch(url, ROBOTS_TOKEN):
            _finish(asset_id, status=AssetStatus.SKIPPED, status_reason="robots")
            stats["skipped_robots"] += 1
            continue

        pacer.wait()
        fetched = fetch(client, url, MAX_FILE_BYTES)
        if fetched.status_code in BLOCK_STATUSES:
            consecutive_blocks += 1
            _finish(
                asset_id,
                status=AssetStatus.BLOCKED,
                http_status=fetched.status_code,
                status_reason=f"HTTP {fetched.status_code}",
            )
            stats["blocked"] += 1
            if consecutive_blocks >= CONSECUTIVE_BLOCKS_TO_STOP:
                stats["stopped_blocked"] = 1
                stats["not_processed"] = len(pending) - index - 1
                break
            continue
        consecutive_blocks = 0
        if not fetched.ok:
            reason = fetched.error or f"HTTP {fetched.status_code}"
            _finish(
                asset_id,
                status=AssetStatus.FAILED,
                http_status=fetched.status_code,
                status_reason=reason[:200],
            )
            stats["failed"] += 1
            continue
        if fetched.truncated:
            _finish(
                asset_id,
                status=AssetStatus.FAILED,
                http_status=fetched.status_code,
                status_reason=f"larger than {MAX_FILE_BYTES // 1_048_576} MB",
            )
            stats["too_large"] += 1
            continue
        if not fetched.body.startswith(b"%PDF"):
            _finish(
                asset_id,
                status=AssetStatus.FAILED,
                http_status=fetched.status_code,
                status_reason="not a PDF (the server sent something else)",
            )
            stats["failed"] += 1
            continue

        digest, relative = store_file(data_dir, "files", fetched.body, ".pdf")
        try:
            extraction = extract_pdf(fetched.body)
        except PdfError as exc:
            _finish(
                asset_id,
                status=AssetStatus.FAILED,
                http_status=fetched.status_code,
                content_sha256=digest,
                file_path=relative,
                status_reason=str(exc)[:200],
            )
            stats["unreadable"] += 1
            continue

        with session_scope() as session:
            asset = session.get(Asset, asset_id)
            asset.status = AssetStatus.OK
            asset.http_status = fetched.status_code
            asset.final_url = fetched.final_url if fetched.final_url != url else None
            asset.content_sha256 = digest
            asset.file_path = relative
            asset.title = extraction.metadata.get("title")
            asset.fetched_at = utcnow()
            counts = Counter(s["visibility"] for s in extraction.segments)
            asset.info = (
                (asset.info or {})
                | extraction.info()
                | {
                    "bytes": len(fetched.body),
                    "segments": dict(counts),
                }
            )
            if extraction.segments:
                session.execute(
                    insert(Segment),
                    [
                        {
                            "asset_id": asset_id,
                            "text": s["text"],
                            "text_source": s["source"],
                            "visibility": s["visibility"],
                            "render_transform": None,
                            "locator": s["locator"],
                            "extractor": EXTRACTOR,
                        }
                        for s in extraction.segments
                    ],
                )
        stats["ok"] += 1
        stats["needs_ocr"] += int(extraction.needs_ocr)
    return dict(stats) | {"found": len(pending)}
