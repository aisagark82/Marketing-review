from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from brandguard.api.deps import SessionDep
from brandguard.api.schemas import (
    AssetDetail,
    AssetOut,
    AssetPage,
    CrawlStart,
    FindingBrief,
    RunOut,
    SegmentOut,
)
from brandguard.core.db import session_scope
from brandguard.core.models import (
    Asset,
    AssetKind,
    Finding,
    Readiness,
    Run,
    RunStatus,
    Segment,
    Site,
)
from brandguard.jobs.queue import get_queue

router = APIRouter(tags=["crawl"])


@router.post("/sites/{site_id}/crawl", response_model=RunOut, status_code=status.HTTP_201_CREATED)
def start_crawl(site_id: int, payload: CrawlStart) -> Run:
    with session_scope() as session:
        site = session.get(Site, site_id)
        if site is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Site {site_id} not found")
        if site.readiness != Readiness.READY:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This site isn't ready to crawl: run the pre-flight check and acknowledge it first",
            )
        active = session.scalar(
            select(Run.id).where(
                Run.site_id == site_id,
                Run.kind.in_(["crawl", "preflight"]),
                Run.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]),
            )
        )
        if active is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Run {active} is still in progress")
        run = Run(
            kind="crawl",
            site_id=site_id,
            params={"crawler": payload.crawler},
            message="Waiting for the worker",
        )
        session.add(run)
        session.flush()
        run_id = run.id
    get_queue().enqueue("crawl", run_id)
    with session_scope() as session:
        return session.get(Run, run_id)


@router.get("/runs/{run_id}/assets", response_model=AssetPage)
def list_assets(
    run_id: int,
    session: SessionDep,
    kind: str | None = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AssetPage:
    if session.get(Run, run_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run {run_id} not found")
    query = select(Asset).where(Asset.run_id == run_id)
    if kind:
        query = query.where(Asset.kind.in_(kind.split(",")))
    if status_:
        query = query.where(Asset.status.in_(status_.split(",")))
    if q:
        query = query.where(Asset.url.contains(q) | Asset.title.contains(q))
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    items = session.scalars(query.order_by(Asset.id).limit(limit).offset(offset)).all()
    counts = dict(
        session.execute(
            select(Finding.asset_id, func.count())
            .where(Finding.asset_id.in_([a.id for a in items]))
            .group_by(Finding.asset_id)
        ).all()
    )
    return AssetPage(
        total=total,
        items=[
            AssetOut.model_validate(a).model_copy(update={"findings": counts.get(a.id, 0)})
            for a in items
        ],
    )


@router.get("/assets/{asset_id}", response_model=AssetDetail)
def read_asset(
    asset_id: int,
    session: SessionDep,
    visibility: str | None = None,
    source: str | None = None,
) -> AssetDetail:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Asset {asset_id} not found")
    segments = select(Segment).where(Segment.asset_id == asset_id)
    if visibility:
        segments = segments.where(Segment.visibility == visibility)
    if source:
        segments = segments.where(Segment.text_source == source)
    found_here = select(Asset).where(Asset.found_on_id == asset_id, Asset.kind != AssetKind.PAGE)
    by_segment: dict[int, list[FindingBrief]] = {}
    for finding in session.scalars(
        select(Finding).where(Finding.asset_id == asset_id).order_by(Finding.start)
    ):
        by_segment.setdefault(finding.segment_id, []).append(FindingBrief.model_validate(finding))
    segment_rows = [
        SegmentOut.model_validate(s).model_copy(update={"findings": by_segment.get(s.id, [])})
        for s in session.scalars(segments.order_by(Segment.id))
    ]
    return AssetDetail(
        **AssetOut.model_validate(asset).model_dump()
        | {"findings": sum(len(v) for v in by_segment.values())},
        segments=segment_rows,
        files=[AssetOut.model_validate(a) for a in session.scalars(found_here.order_by(Asset.id))],
    )


@router.post("/runs/{run_id}/evaluate", response_model=RunOut, status_code=201)
def reevaluate(run_id: int) -> Run:
    """Check an earlier crawl again with the current rules."""
    with session_scope() as session:
        crawl_run = session.get(Run, run_id)
        if crawl_run is None or crawl_run.kind != "crawl":
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Crawl run {run_id} not found")
        if crawl_run.status in (RunStatus.QUEUED, RunStatus.RUNNING):
            raise HTTPException(status.HTTP_409_CONFLICT, "The crawl is still running")
        run = Run(
            kind="evaluate",
            site_id=crawl_run.site_id,
            params={"crawl_run_id": run_id},
            message="Waiting for the worker",
        )
        session.add(run)
        session.flush()
        new_id = run.id
    get_queue().enqueue("evaluate", new_id)
    with session_scope() as session:
        return session.get(Run, new_id)
