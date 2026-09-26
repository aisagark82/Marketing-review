from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from brandguard.api.deps import SessionDep
from brandguard.api.schemas import Acknowledgement, BrandOut, RunOut, SiteConfig, SiteOut
from brandguard.core.db import session_scope, utcnow
from brandguard.core.models import Brand, Readiness, Run, RunStatus, Site
from brandguard.jobs.queue import get_queue

router = APIRouter(tags=["sites"])


def _get_site_or_404(session: Session, site_id: int) -> Site:
    site = session.get(Site, site_id)
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Site {site_id} not found")
    return site


def _check_brand(session: Session, brand_id: int) -> None:
    if session.get(Brand, brand_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Brand {brand_id} not found")


@router.get("/brands", response_model=list[BrandOut])
def list_brands(session: SessionDep) -> list[Brand]:
    return list(session.scalars(select(Brand).order_by(Brand.name)))


@router.get("/sites", response_model=list[SiteOut])
def list_sites(session: SessionDep) -> list[Site]:
    return list(session.scalars(select(Site).order_by(Site.name)))


@router.post("/sites", response_model=SiteOut, status_code=status.HTTP_201_CREATED)
def create_site(config: SiteConfig, session: SessionDep) -> Site:
    _check_brand(session, config.brand_id)
    site = Site(**config.model_dump())
    session.add(site)
    session.flush()
    session.refresh(site)
    return site


@router.get("/sites/{site_id}", response_model=SiteOut)
def read_site(site_id: int, session: SessionDep) -> Site:
    return _get_site_or_404(session, site_id)


@router.put("/sites/{site_id}", response_model=SiteOut)
def update_site(site_id: int, config: SiteConfig, session: SessionDep) -> Site:
    site = _get_site_or_404(session, site_id)
    _check_brand(session, config.brand_id)
    for name, value in config.model_dump().items():
        setattr(site, name, value)
    # Changing what the pre-flight check covered withdraws the acknowledgement;
    # readiness then reports "stale" until the check is run again.
    if site.preflight_fingerprint != site.fingerprint():
        site.preflight_acknowledged_at = None
    session.flush()
    session.refresh(site)
    return site


@router.post("/sites/{site_id}/preflight", response_model=RunOut, status_code=201)
def start_preflight(site_id: int) -> Run:
    with session_scope() as session:
        _get_site_or_404(session, site_id)
        active = session.scalar(
            select(Run.id).where(
                Run.site_id == site_id,
                Run.kind == "preflight",
                Run.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]),
            )
        )
        if active is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"A pre-flight check is already running (run {active})"
            )
        run = Run(kind="preflight", site_id=site_id, message="Waiting for the worker")
        session.add(run)
        session.flush()
        run_id = run.id
    get_queue().enqueue("preflight", run_id)
    with session_scope() as session:
        return session.get(Run, run_id)


@router.post("/sites/{site_id}/preflight/acknowledge", response_model=SiteOut)
def acknowledge_preflight(site_id: int, _ack: Acknowledgement, session: SessionDep) -> Site:
    site = _get_site_or_404(session, site_id)
    reasons = {
        Readiness.NEEDS_PREFLIGHT: "Run the pre-flight check first",
        Readiness.STALE: "The site settings changed; run the pre-flight check again",
        Readiness.BLOCKED: "The pre-flight check found blockers, so crawling isn't possible",
    }
    if site.readiness in reasons:
        raise HTTPException(status.HTTP_409_CONFLICT, reasons[site.readiness])
    site.preflight_acknowledged_at = utcnow()
    return site
