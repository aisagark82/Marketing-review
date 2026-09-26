import asyncio

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from brandguard.api.deps import SessionDep
from brandguard.api.schemas import RunCreate, RunOut
from brandguard.core.db import session_scope, utcnow
from brandguard.core.models import Run, RunStatus
from brandguard.jobs.queue import get_queue

router = APIRouter(prefix="/runs", tags=["runs"])

EVENT_POLL_SECONDS = 0.5


def _get_run_or_404(session: Session, run_id: int) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run {run_id} not found")
    return run


@router.get("", response_model=list[RunOut])
def list_runs(session: SessionDep, limit: int = 50) -> list[Run]:
    return list(session.scalars(select(Run).order_by(Run.id.desc()).limit(limit)))


@router.post("", response_model=RunOut, status_code=status.HTTP_201_CREATED)
def create_run(payload: RunCreate) -> Run:
    with session_scope() as session:
        run = Run(kind=payload.kind, message="Waiting for the worker")
        session.add(run)
        session.flush()
        run_id = run.id
    # Enqueue after commit so the worker can see the row.
    get_queue().enqueue(payload.kind, run_id)
    with session_scope() as session:
        return _get_run_or_404(session, run_id)


@router.get("/{run_id}", response_model=RunOut)
def read_run(run_id: int, session: SessionDep) -> Run:
    return _get_run_or_404(session, run_id)


@router.post("/{run_id}/cancel", response_model=RunOut)
def cancel_run(run_id: int, session: SessionDep) -> Run:
    run = _get_run_or_404(session, run_id)
    if run.status in RunStatus.TERMINAL:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Run {run_id} is already {run.status}")
    if run.status == RunStatus.QUEUED:
        # Not picked up yet: the task sees the terminal status and exits immediately.
        run.status = RunStatus.CANCELLED
        run.finished_at = utcnow()
        run.message = "Cancelled before it started"
    run.cancel_requested = True
    return run


def _load_run_json(run_id: int) -> tuple[str, bool] | None:
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            return None
        return RunOut.model_validate(run).model_dump_json(), run.status in RunStatus.TERMINAL


@router.get("/{run_id}/events")
async def run_events(run_id: int, request: Request) -> StreamingResponse:
    """Server-Sent Events: pushes the run whenever it changes, until it finishes."""
    if await run_in_threadpool(_load_run_json, run_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run {run_id} not found")

    async def stream():
        last = None
        while not await request.is_disconnected():
            loaded = await run_in_threadpool(_load_run_json, run_id)
            if loaded is None:
                return
            payload, finished = loaded
            if payload != last:
                yield f"event: run\ndata: {payload}\n\n"
                last = payload
            if finished:
                return
            await asyncio.sleep(EVENT_POLL_SECONDS)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
