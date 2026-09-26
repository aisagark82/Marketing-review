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

    summary = {
        "assets_checked": 0,
        "segments_checked": 0,
        "violations": 0,
        "ambiguous": 0,
        "assets_with_findings": 0,
    }
    by = {name: Counter() for name in ("kind", "severity", "visibility", "asset_kind")}
    top = Counter()

    for index, asset in enumerate(assets):
        if on_progress and index % 20 == 0:
            on_progress(index, len(assets))
        # A PDF has no declared language; use the page that linked to it.
        language = asset.language or page_language.get(asset.found_on_id)
        rows = []
        with session_scope() as session:
            segments = session.execute(
                select(Segment.id, Segment.text, Segment.visibility).where(
                    Segment.asset_id == asset.id
                )
            ).all()
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
                        by["kind"][match.kind] += 1
                        by["severity"][match.severity] += 1
                        by["visibility"][segment.visibility] += 1
                        by["asset_kind"][asset.kind] += 1
                        if match.status == FindingStatus.VIOLATION:
                            summary["violations"] += 1
                            top[match.matched] += 1
                        else:
                            summary["ambiguous"] += 1
            if rows:
                session.execute(insert(Finding), rows)
                summary["assets_with_findings"] += 1
        summary["assets_checked"] += 1
        summary["segments_checked"] += len(segments)

    return (
        summary
        | {f"by_{name}": dict(counter) for name, counter in by.items()}
        | {
            "top_matches": top.most_common(TOP_MATCHES),
            "rules": rules_used,
        }
    )
