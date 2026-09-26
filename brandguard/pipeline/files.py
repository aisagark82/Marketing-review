"""Download and extract the files a crawl found: PDFs, and images when Settings allow it.
Other kinds (Office, video, audio) stay "discovered" for now.

Same politeness as pages: robots.txt, the crawl's pace, honest User-Agent, and a stop after
repeated refusals.
"""

import io
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import httpx
from defusedxml import ElementTree
from PIL import Image as PILImage
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


# --- images (Gemini reads raster images; SVG text is read directly) --------------------------
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MIN_IMAGE_SIDE = 48  # icons, spacers and tracking pixels carry no brand text worth a request
GEMINI_IMAGE_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
SVG_TEXT_TAGS = ("text", "tspan", "textPath")


def svg_text(data: bytes) -> list[str]:
    """Text elements of an SVG, read without an AI model."""
    root = ElementTree.fromstring(data)
    lines = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag in SVG_TEXT_TAGS and element.text and element.text.strip():
            lines.append(" ".join(element.text.split()))
    return lines


def prepare_raster(data: bytes) -> tuple[bytes, str] | None:
    """(bytes, MIME type) Gemini accepts, or None if the image is too small or unreadable."""
    try:
        with PILImage.open(io.BytesIO(data)) as image:
            if min(image.size) < MIN_IMAGE_SIDE:
                return None
            if image.format in GEMINI_IMAGE_TYPES:
                return data, GEMINI_IMAGE_TYPES[image.format]
            image.seek(0)  # first frame of a GIF
            converted = io.BytesIO()
            image.convert("RGBA").save(converted, format="PNG")
            return converted.getvalue(), "image/png"
    except (PILImage.UnidentifiedImageError, OSError, ValueError):
        return None


def process_images(
    run_id: int,
    client: httpx.Client,
    policy: CrawlPolicy,
    pacer: Pacer,
    data_dir: Path,
    read_text: Callable[[bytes, str], list[str]],
    max_images: int,
    should_stop: Callable[[], bool],
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Download in-scope images (visible ones first) and extract their text."""
    with session_scope() as session:
        rows = session.execute(
            select(Asset.id, Asset.url, Asset.info)
            .where(
                Asset.run_id == run_id,
                Asset.kind == AssetKind.IMAGE,
                Asset.status == AssetStatus.DISCOVERED,
            )
            .order_by(Asset.id)
        ).all()
    # Images a visitor sees matter most when there's a cap.
    pending = sorted(rows, key=lambda r: not (r.info or {}).get("visible"))
    stats: Counter = Counter()
    consecutive_blocks = 0
    for index, (asset_id, url, info) in enumerate(pending):
        if index >= max_images:
            stats["over_image_limit"] = len(pending) - index
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
        fetched = fetch(client, url, MAX_IMAGE_BYTES)
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
                break
            continue
        consecutive_blocks = 0
        if not fetched.ok or fetched.truncated:
            reason = fetched.error or (
                "too large" if fetched.truncated else f"HTTP {fetched.status_code}"
            )
            _finish(
                asset_id,
                status=AssetStatus.FAILED,
                http_status=fetched.status_code,
                status_reason=reason[:200],
            )
            stats["failed"] += 1
            continue

        is_svg = "svg" in fetched.headers.get("content-type", "") or url.lower().endswith(".svg")
        suffix = ".svg" if is_svg else ".img"
        digest, relative = store_file(data_dir, "images", fetched.body, suffix)
        extractor = "svg-text"
        try:
            if is_svg:
                lines = svg_text(fetched.body)
            else:
                prepared = prepare_raster(fetched.body)
                if prepared is None:
                    _finish(
                        asset_id,
                        status=AssetStatus.SKIPPED,
                        status_reason="too small or unreadable",
                        content_sha256=digest,
                        file_path=relative,
                    )
                    stats["too_small"] += 1
                    continue
                lines = read_text(*prepared)
                extractor = "gemini-vision"
        except Exception as exc:  # unreadable SVG, Gemini error for this image
            _finish(
                asset_id,
                status=AssetStatus.FAILED,
                status_reason=f"could not read text: {exc}"[:200],
                content_sha256=digest,
                file_path=relative,
            )
            stats["failed"] += 1
            if type(exc).__name__ in ("AILimitReached", "AIUnavailable"):
                stats["stopped_ai"] = 1
                break
            continue

        visibility = "visible" if (info or {}).get("visible") else "hidden"
        with session_scope() as session:
            asset = session.get(Asset, asset_id)
            asset.status, asset.fetched_at = AssetStatus.OK, utcnow()
            asset.http_status, asset.content_sha256, asset.file_path = (
                fetched.status_code,
                digest,
                relative,
            )
            asset.info = (asset.info or {}) | {
                "bytes": len(fetched.body),
                "segments": {visibility: len(lines)},
            }
            if lines:
                session.execute(
                    insert(Segment),
                    [
                        {
                            "asset_id": asset_id,
                            "text": line,
                            "text_source": "image_text",
                            "visibility": visibility,
                            "render_transform": None,
                            "locator": {"line": number},
                            "extractor": extractor,
                        }
                        for number, line in enumerate(lines, start=1)
                    ],
                )
        stats["ok"] += 1
        stats["with_text"] += int(bool(lines))
    return dict(stats) | {"found": len(pending)}
