"""Evaluate a crawl run's text against the brand's rules and store the findings."""

from collections import Counter
from collections.abc import Callable

from sqlalchemy import delete, insert, select

from brandguard.core.db import session_scope, utcnow
from brandguard.core.models import (
    Asset,
    AssetStatus,
    Finding,
    FindingStatus,
    Rule,
    Run,
    Segment,
    Visibility,
)
from brandguard.rules.service import checker

TOP_MATCHES = 15


def evaluate_run(
    crawl_run_id: int,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Replace the run's findings with a fresh evaluation using the current rule versions."""
    with session_scope() as session:
        run = session.get(Run, crawl_run_id)
        rules = session.scalars(
            select(Rule).where(Rule.brand_id == run.site.brand_id, Rule.enabled)
        ).all()
        checks = [(r.id, r.version, checker(r.type, r.config, r.severity)) for r in rules]
        rules_used = [{"id": r.id, "key": r.key, "version": r.version} for r in rules]
        assets = session.execute(
            select(Asset.id, Asset.kind, Asset.language, Asset.found_on_id)
            .where(Asset.run_id == crawl_run_id, Asset.status == AssetStatus.OK)
            .order_by(Asset.id)
        ).all()
        page_language = {a.id: a.language for a in assets}
        session.execute(delete(Finding).where(Finding.run_id == crawl_run_id))

    segments_checked = 0
    for index, asset in enumerate(assets):
        if on_progress and index % 20 == 0:
            on_progress(index, len(assets))
        # PDFs and images have no declared language; use the page that linked to them.
        language = asset.language or page_language.get(asset.found_on_id)
        rows = []
        with session_scope() as session:
            segments = session.execute(
                select(Segment.id, Segment.text, Segment.visibility).where(
                    Segment.asset_id == asset.id
                )
            ).all()
            segments_checked += len(segments)
            for segment in segments:
                if segment.visibility == Visibility.SPOKEN:
                    continue  # speech is checked for mentions, not spelling (design §5.5)
                for rule_id, version, check in checks:
                    for match in check.check(segment.text, language):
                        rows.append(
                            {
                                "run_id": crawl_run_id,
                                "asset_id": asset.id,
                                "segment_id": segment.id,
                                "rule_id": rule_id,
                                "rule_version": version,
                                "kind": match.kind,
                                "status": match.status,
                                "severity": match.severity,
                                "matched_text": match.matched,
                                "expected": match.expected,
                                "start": match.start,
                                "end": match.end,
                                "confidence": match.confidence,
                                "note": match.note,
                                "created_at": utcnow(),
                            }
                        )
            if rows:
                session.execute(insert(Finding), rows)

    return summarize_findings(crawl_run_id) | {
        "assets_checked": len(assets),
        "segments_checked": segments_checked,
        "rules": rules_used,
    }


def summarize_findings(crawl_run_id: int) -> dict:
    """Counts for the run page, read back from the stored findings (so they reflect Gemini's
    later verdicts too). The "by_" breakdowns count every finding, whatever its status."""
    with session_scope() as session:
        rows = session.execute(
            select(
                Finding.asset_id,
                Finding.kind,
                Finding.status,
                Finding.severity,
                Finding.matched_text,
                Segment.visibility,
                Asset.kind,
            )
            .join(Segment, Finding.segment_id == Segment.id)
            .join(Asset, Finding.asset_id == Asset.id)
            .where(Finding.run_id == crawl_run_id)
        ).all()
    statuses = Counter(r[2] for r in rows)
    return {
        "violations": statuses[FindingStatus.VIOLATION],
        "ambiguous": statuses[FindingStatus.AMBIGUOUS],
        "dismissed": statuses[FindingStatus.DISMISSED],
        "assets_with_findings": len({r[0] for r in rows if r[2] != FindingStatus.DISMISSED}),
        "by_kind": dict(Counter(r[1] for r in rows if r[2] != FindingStatus.DISMISSED)),
        "by_severity": dict(Counter(r[3] for r in rows if r[2] != FindingStatus.DISMISSED)),
        "by_visibility": dict(Counter(r[5] for r in rows if r[2] != FindingStatus.DISMISSED)),
        "by_asset_kind": dict(Counter(r[6] for r in rows if r[2] != FindingStatus.DISMISSED)),
        "top_matches": Counter(r[4] for r in rows if r[2] == FindingStatus.VIOLATION).most_common(
            TOP_MATCHES
        ),
    }
