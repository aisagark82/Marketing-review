import csv
import io
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from brandguard.api.deps import SessionDep
from brandguard.core.models import Finding, Rule, Run, Site
from brandguard.core.paths import get_paths
from brandguard.reporting import (
    compliance,
    crawler_comparison,
    evidence,
    facets,
    filter_rows,
    findings_with_changes,
    latest_crawl_run,
    neighbours,
)

router = APIRouter(tags=["findings"])

CSV_COLUMNS = [
    "finding_id",
    "status",
    "type",
    "severity",
    "found",
    "expected",
    "change",
    "visibility",
    "text_source",
    "asset_kind",
    "url",
    "page_title",
    "pdf_page",
    "text",
    "note",
    "rule_version",
]


def _run_or_latest(session: Session, run_id: int | None) -> Run | None:
    if run_id is None:
        return latest_crawl_run(session)
    run = session.get(Run, run_id)
    if run is None or run.kind != "crawl":
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Crawl run {run_id} not found")
    return run


def _filtered(session: Session, run: Run, filters: dict, q: str | None):
    rows, changes = findings_with_changes(session, run)
    return rows, filter_rows(rows, filters, q), changes


def _filters(status_, kind, severity, change, visibility, source, asset_kind) -> dict:
    return {
        "status": status_,
        "kind": kind,
        "severity": severity,
        "change": change,
        "visibility": visibility,
        "source": source,
        "asset_kind": asset_kind,
    }


Filter = Annotated[str | None, Query()]


@router.get("/finding-runs")
def finding_runs(session: SessionDep) -> list[dict]:
    """Crawl runs that have been evaluated, newest first (for run pickers)."""
    runs = session.scalars(select(Run).where(Run.kind == "crawl").order_by(Run.id.desc())).all()
    return [
        {
            "id": r.id,
            "site_id": r.site_id,
            "site_name": r.site_name,
            "crawler": (r.params or {}).get("crawler"),
            "status": r.status,
            "started_at": r.started_at,
            "violations": r.stats["findings"]["violations"],
            "to_review": r.stats["findings"]["ambiguous"],
        }
        for r in runs
        if (r.stats or {}).get("findings") is not None
    ]


@router.get("/findings")
def list_findings(
    session: SessionDep,
    run_id: int | None = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    kind: Filter = None,
    severity: Filter = None,
    change: Filter = None,
    visibility: Filter = None,
    source: Filter = None,
    asset_kind: Filter = None,
    q: Filter = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    run = _run_or_latest(session, run_id)
    if run is None:
        return {"run": None, "total": 0, "items": [], "facets": {}, "changes": {}}
    filters = _filters(status_, kind, severity, change, visibility, source, asset_kind)
    rows, selected, changes = _filtered(session, run, filters, q)
    return {
        "run": {
            "id": run.id,
            "site_id": run.site_id,
            "site_name": run.site_name,
            "crawler": (run.params or {}).get("crawler"),
            "started_at": run.started_at,
        },
        "total": len(selected),
        "items": selected[offset : offset + limit],
        "facets": facets(rows),
        "changes": changes,
    }


@router.get("/findings.csv")
def export_findings(
    session: SessionDep,
    run_id: int | None = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    kind: Filter = None,
    severity: Filter = None,
    change: Filter = None,
    visibility: Filter = None,
    source: Filter = None,
    asset_kind: Filter = None,
    q: Filter = None,
) -> StreamingResponse:
    run = _run_or_latest(session, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No evaluated crawl yet")
    filters = _filters(status_, kind, severity, change, visibility, source, asset_kind)
    _, selected, _ = _filtered(session, run, filters, q)
    buffer = io.StringIO()
    buffer.write("﻿")  # BOM: Excel then reads the file as UTF-8 (Japanese, Chinese ...)
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for r in selected:
        writer.writerow(
            [
                r["id"],
                r["status"],
                r["kind"],
                r["severity"],
                r["matched_text"],
                r["expected"],
                r["change"] or "",
                r["segment"]["visibility"],
                r["segment"]["source"],
                r["asset"]["kind"],
                r["asset"]["url"],
                r["asset"]["title"] or "",
                (r["segment"]["locator"] or {}).get("page") or "",
                r["segment"]["text"],
                r["note"] or "",
                r["rule_version"],
            ]
        )
    name = f"brandguard-findings-run{run.id}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/findings/{finding_id}")
def read_finding(finding_id: int, session: SessionDep) -> dict:
    finding = session.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Finding {finding_id} not found")
    run = session.get(Run, finding.run_id)
    rows, _ = findings_with_changes(session, run)
    row = next(r for r in rows if r["id"] == finding_id)
    rule = session.get(Rule, finding.rule_id)
    previous_id, next_id = neighbours(session, finding)
    return row | {
        "run": {
            "id": run.id,
            "site_id": run.site_id,
            "site_name": run.site_name,
            "crawler": (run.params or {}).get("crawler"),
        },
        "rule": {
            "id": rule.id,
            "key": rule.key,
            "name": rule.name,
            "current_version": rule.version,
        },
        "evidence": evidence(session, get_paths().data_dir, finding),
        "previous_id": previous_id,
        "next_id": next_id,
    }


@router.get("/runs/{run_id}/compliance")
def run_compliance(run_id: int, session: SessionDep) -> dict:
    run = _run_or_latest(session, run_id)
    if (run.stats or {}).get("findings") is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This crawl hasn't been evaluated")
    return compliance(session, run)


@router.get("/compliance")
def latest_compliance(session: SessionDep, site_id: int | None = None) -> dict | None:
    run = latest_crawl_run(session, site_id)
    return compliance(session, run) if run else None


@router.get("/sites/{site_id}/comparison")
def comparison(site_id: int, session: SessionDep) -> dict:
    if session.get(Site, site_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Site {site_id} not found")
    return crawler_comparison(session, site_id)
