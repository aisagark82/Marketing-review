"""Compliance scores, findings lists, run-to-run changes and the crawler comparison.

Scoring (design §6.3, D8): a finding weighs severity (high 10, medium 3, low 1) times its
visibility factor (all 1.0, so hidden and metadata text count fully). An asset scores
100 minus its weights (floor 0); the site scores the average over the pages and PDFs that
were read. Findings "to review" (near-misses) don't count until they're confirmed.
"""

import gzip
import json
import re
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from brandguard.core.models import (
    Asset,
    AssetStatus,
    Finding,
    FindingStatus,
    Run,
    RunStatus,
    Segment,
)

SEVERITY_WEIGHT = {"high": 10, "medium": 3, "low": 1}
VISIBILITY_FACTOR = {"visible": 1.0, "hidden": 1.0, "metadata": 1.0, "spoken": 1.0}
WORST_ASSETS = 10
SNIPPET_CHARS = 1500
FINISHED = (RunStatus.COMPLETED, RunStatus.BLOCKED)


def latest_crawl_run(session: Session, site_id: int | None = None, crawler: str | None = None):
    query = select(Run).where(Run.kind == "crawl", Run.status.in_(FINISHED))
    if site_id is not None:
        query = query.where(Run.site_id == site_id)
    runs = session.scalars(query.order_by(Run.id.desc())).all()
    for run in runs:
        if (run.stats or {}).get("findings") is None:
            continue
        if crawler is None or (run.params or {}).get("crawler") == crawler:
            return run
    return None


def previous_crawl_run(session: Session, run: Run) -> Run | None:
    query = (
        select(Run)
        .where(
            Run.kind == "crawl",
            Run.site_id == run.site_id,
            Run.id < run.id,
            Run.status.in_(FINISHED),
        )
        .order_by(Run.id.desc())
    )
    return next((r for r in session.scalars(query) if (r.stats or {}).get("findings")), None)


def _rows(session: Session, run_id: int) -> list[dict]:
    query = (
        select(
            Finding,
            Asset.url,
            Asset.title,
            Asset.kind,
            Segment.text,
            Segment.text_source,
            Segment.visibility,
            Segment.locator,
        )
        .join(Asset, Finding.asset_id == Asset.id)
        .join(Segment, Finding.segment_id == Segment.id)
        .where(Finding.run_id == run_id)
        .order_by(Asset.id, Finding.segment_id, Finding.start)
    )
    rows = []
    for finding, url, title, asset_kind, text, source, visibility, locator in session.execute(
        query
    ):
        rows.append(
            {
                "id": finding.id,
                "kind": finding.kind,
                "status": finding.status,
                "severity": finding.severity,
                "matched_text": finding.matched_text,
                "expected": finding.expected,
                "note": finding.note,
                "start": finding.start,
                "end": finding.end,
                "confidence": finding.confidence,
                "rule_id": finding.rule_id,
                "rule_version": finding.rule_version,
                "asset": {"id": finding.asset_id, "url": url, "title": title, "kind": asset_kind},
                "segment": {
                    "id": finding.segment_id,
                    "text": text,
                    "source": source,
                    "visibility": visibility,
                    "locator": locator,
                },
            }
        )
    return rows


def _key(row: dict) -> tuple:
    """Identity of a finding across runs (same page, same text, same problem)."""
    return (
        row["asset"]["url"],
        row["kind"],
        row["matched_text"],
        row["segment"]["source"],
        row["segment"]["text"],
    )


def findings_with_changes(session: Session, run: Run) -> tuple[list[dict], dict]:
    rows = _rows(session, run.id)
    previous = previous_crawl_run(session, run)
    if previous is None:
        for row in rows:
            row["change"] = None
        return rows, {"previous_run_id": None, "new": 0, "persisting": 0, "fixed": 0}
    before = Counter(_key(r) for r in _rows(session, previous.id))
    now = Counter(_key(r) for r in rows)
    for row in rows:
        row["change"] = "persisting" if before[_key(row)] else "new"
    fixed = sum((before - now).values())
    changes = Counter(r["change"] for r in rows)
    return rows, {
        "previous_run_id": previous.id,
        "new": changes["new"],
        "persisting": changes["persisting"],
        "fixed": fixed,
    }


FILTERS = ("status", "kind", "severity", "change")
NESTED_FILTERS = {
    "visibility": ("segment", "visibility"),
    "source": ("segment", "source"),
    "asset_kind": ("asset", "kind"),
}


def facet_value(row: dict, name: str):
    if name in NESTED_FILTERS:
        outer, inner = NESTED_FILTERS[name]
        return row[outer][inner]
    return row[name]


def filter_rows(rows: list[dict], filters: dict[str, str | None], q: str | None) -> list[dict]:
    for name, value in filters.items():
        if value:
            wanted = set(value.split(","))
            rows = [r for r in rows if facet_value(r, name) in wanted]
    if q:
        needle = q.casefold()
        rows = [
            r
            for r in rows
            if needle in r["matched_text"].casefold()
            or needle in r["segment"]["text"].casefold()
            or needle in r["asset"]["url"].casefold()
        ]
    return rows


def facets(rows: list[dict]) -> dict[str, dict[str, int]]:
    names = (*FILTERS, *NESTED_FILTERS)
    return {
        name: dict(Counter(facet_value(r, name) for r in rows if facet_value(r, name)))
        for name in names
    }


def compliance(session: Session, run: Run) -> dict:
    rows, changes = findings_with_changes(session, run)
    assets = session.execute(
        select(Asset.id, Asset.url, Asset.title, Asset.kind).where(
            Asset.run_id == run.id, Asset.status == AssetStatus.OK
        )
    ).all()
    weights: Counter = Counter()
    violations_per_asset: Counter = Counter()
    high_assets: set[int] = set()
    violations = [r for r in rows if r["status"] == FindingStatus.VIOLATION]
    for row in violations:
        asset_id = row["asset"]["id"]
        weights[asset_id] += SEVERITY_WEIGHT.get(row["severity"], 1) * VISIBILITY_FACTOR.get(
            row["segment"]["visibility"], 1.0
        )
        violations_per_asset[asset_id] += 1
        if row["severity"] == "high":
            high_assets.add(asset_id)
    scores = {a.id: max(0.0, 100.0 - weights[a.id]) for a in assets}
    worst = sorted((a for a in assets if weights[a.id]), key=lambda a: (scores[a.id], a.id))
    return {
        "run": {
            "id": run.id,
            "crawler": (run.params or {}).get("crawler"),
            "site_id": run.site_id,
            "site_name": run.site_name,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "rules": (run.stats or {}).get("findings", {}).get("rules", []),
        },
        "score": round(sum(scores.values()) / len(scores), 1) if scores else None,
        "clean_share": round(100 * (len(assets) - len(high_assets)) / len(assets), 1)
        if assets
        else None,
        "assets_checked": len(assets),
        "assets_with_violations": len(violations_per_asset),
        "violations": len(violations),
        "to_review": sum(1 for r in rows if r["status"] == FindingStatus.AMBIGUOUS),
        "by_visibility": dict(Counter(r["segment"]["visibility"] for r in violations)),
        "by_asset_kind": dict(Counter(r["asset"]["kind"] for r in violations)),
        "by_source": dict(Counter(r["segment"]["source"] for r in violations).most_common(10)),
        "by_kind": dict(Counter(r["kind"] for r in violations)),
        "top_matches": Counter(r["matched_text"] for r in violations).most_common(10),
        "worst_assets": [
            {
                "id": a.id,
                "url": a.url,
                "title": a.title,
                "kind": a.kind,
                "score": round(scores[a.id], 1),
                "violations": violations_per_asset[a.id],
            }
            for a in worst[:WORST_ASSETS]
        ],
        "changes": changes,
    }


def crawler_comparison(session: Session, site_id: int) -> dict:
    """The latest finished crawl of the site by each crawler, side by side (design §5.1)."""
    from brandguard.pipeline.crawl.adapters import CRAWLERS

    result: dict = {"crawlers": {}, "only_in": {}}
    pages: dict[str, set[str]] = {}
    for crawler in CRAWLERS:
        run = latest_crawl_run(session, site_id, crawler)
        if run is None:
            continue
        stats = run.stats or {}
        scored = compliance(session, run)
        ok_pages = set(
            session.scalars(
                select(Asset.url).where(
                    Asset.run_id == run.id, Asset.kind == "page", Asset.status == AssetStatus.OK
                )
            )
        )
        pages[crawler] = ok_pages
        result["crawlers"][crawler] = {
            "run_id": run.id,
            "status": run.status,
            "version": stats.get("crawler_version"),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "pages_ok": stats.get("pages", {}).get("ok", 0),
            "pages_failed": stats.get("pages", {}).get("failed", 0),
            "pages_blocked": stats.get("pages", {}).get("blocked", 0),
            "files_found": sum(stats.get("files", {}).values()),
            "pdfs_read": stats.get("documents", {}).get("ok", 0),
            "segments_visible": stats.get("segments", {}).get("visible", 0),
            "segments_hidden": stats.get("segments", {}).get("hidden", 0),
            "segments_metadata": stats.get("segments", {}).get("metadata", 0),
            "violations": scored["violations"],
            "to_review": scored["to_review"],
            "score": scored["score"],
            "pages_runtime_s": stats.get("pages_runtime_s", stats.get("runtime_s")),
            "runtime_s": stats.get("runtime_s"),
            "peak_rss_mb": stats.get("peak_rss_mb"),
            "cpu_s": stats.get("cpu_s"),
            "errors": len(stats.get("errors", [])),
        }
    if len(pages) == 2:
        (a, a_pages), (b, b_pages) = pages.items()
        result["only_in"] = {a: sorted(a_pages - b_pages)[:50], b: sorted(b_pages - a_pages)[:50]}
    return result


# --- evidence -------------------------------------------------------------------------------
def _page_html(data_dir: Path, html_path: str | None) -> str | None:
    if not html_path:
        return None
    try:
        return gzip.decompress((data_dir / html_path).read_bytes()).decode("utf-8", "replace")
    except OSError:
        return None


def html_snippet(html: str, locator: dict, source: str) -> str | None:
    """The saved page's HTML for the element a segment came from (for hidden/metadata text)."""
    selector = (locator or {}).get("selector")
    if not selector:
        return None
    soup = BeautifulSoup(html, "html.parser")
    if source == "json_ld":
        scripts = soup.select('script[type="application/ld+json"]')
        index = re.search(r"nth-of-type\((\d+)\)", selector)
        position = int(index.group(1)) - 1 if index else 0
        if position >= len(scripts):
            return None
        try:
            return json.dumps(
                json.loads(scripts[position].string or ""), indent=2, ensure_ascii=False
            )[:SNIPPET_CHARS]
        except ValueError:
            return (scripts[position].string or "")[:SNIPPET_CHARS]
    try:
        element = soup.select_one(selector)
    except Exception:  # a selector the parser can't handle
        return None
    return str(element)[:SNIPPET_CHARS] if element is not None else None


def evidence(session: Session, data_dir: Path, finding: Finding) -> dict:
    asset = session.get(Asset, finding.asset_id)
    segment = session.get(Segment, finding.segment_id)
    locator = segment.locator or {}
    result: dict = {"live_url": asset.final_url or asset.url, "asset_kind": asset.kind}
    if asset.kind == "pdf":
        result["pdf"] = {
            "file_path": asset.file_path,
            "page": locator.get("page"),
            "bbox": locator.get("bbox"),
            "page_size": locator.get("page_size"),
            "property": locator.get("property"),
        }
        return result
    if asset.screenshot_path and locator.get("bbox"):
        result["screenshot"] = {
            "path": asset.screenshot_path,
            "bbox": locator["bbox"],
            "page_size": (asset.info or {}).get("size"),
        }
    if segment.visibility != "visible" or "screenshot" not in result:
        html = _page_html(data_dir, asset.html_path)
        snippet = html_snippet(html, locator, segment.text_source) if html else None
        if snippet:
            result["snippet"] = {
                "html": snippet,
                "selector": locator.get("selector"),
                "path": locator.get("path"),
                "attribute": locator.get("attribute"),
            }
    return result


def neighbours(session: Session, finding: Finding) -> tuple[int | None, int | None]:
    ids = session.scalars(
        select(Finding.id)
        .where(Finding.run_id == finding.run_id)
        .order_by(Finding.asset_id, Finding.segment_id, Finding.start)
    ).all()
    index = ids.index(finding.id)
    return (ids[index - 1] if index else None, ids[index + 1] if index + 1 < len(ids) else None)
