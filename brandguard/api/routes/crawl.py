from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from brandguard.api.deps import SessionDep
from brandguard.api.schemas import AssetDetail, AssetOut, AssetPage, CrawlStart, RunOut
from brandguard.core.db import session_scope
from brandguard.core.models import Asset, AssetKind, Readiness, Run, RunStatus, Segment, Site
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
        query = query.where(Asset.kind == kind)
    if status_:
        query = query.where(Asset.status.in_(status_.split(",")))
    if q:
        query = query.where(Asset.url.contains(q) | Asset.title.contains(q))
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    items = session.scalars(query.order_by(Asset.id).limit(limit).offset(offset)).all()
    return AssetPage(total=total, items=[AssetOut.model_validate(a) for a in items])


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
    return AssetDetail(
        **AssetOut.model_validate(asset).model_dump(),
        segments=list(session.scalars(segments.order_by(Segment.id))),
        files=[AssetOut.model_validate(a) for a in session.scalars(found_here.order_by(Asset.id))],
    )
