"""Background tasks.

Step 1 only has a self-test run that proves the full loop works:
UI -> API -> queue -> worker -> database -> live progress in the UI.
Crawl, extract and evaluate tasks are added in later steps.
"""

import logging
import time
import uuid
from collections.abc import Callable

from sqlalchemy import text

from brandguard.core.db import session_scope, utcnow
from brandguard.core.models import Run, RunStatus
from brandguard.core.paths import get_paths

log = logging.getLogger(__name__)

SELFTEST_STEPS = ("database", "storage", "worker")
TICKS_PER_STEP = 10
TICK_SECONDS = 0.1


class _Cancelled(Exception):
    pass


def _check_database() -> None:
    with session_scope() as session:
        session.execute(text("SELECT 1"))


def _check_storage() -> None:
    probe = get_paths().data_dir / f".probe-{uuid.uuid4().hex}"
    probe.write_bytes(b"ok")
    probe.unlink()


def _check_worker() -> None:
    # Reaching this point means a worker picked the task up from the queue.
    return None


_CHECKS: dict[str, Callable[[], None]] = {
    "database": _check_database,
    "storage": _check_storage,
    "worker": _check_worker,
}


def _update(run_id: int, **fields) -> None:
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run.cancel_requested:
            raise _Cancelled
        for name, value in fields.items():
            setattr(run, name, value)


def _finish(run_id: int, status: str, **fields) -> None:
    with session_scope() as session:
        run = session.get(Run, run_id)
        run.status = status
        run.finished_at = utcnow()
        for name, value in fields.items():
            setattr(run, name, value)


def selftest(run_id: int) -> None:
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None or run.status in RunStatus.TERMINAL:
            return
        run.status = RunStatus.RUNNING
        run.started_at = utcnow()
        run.total = len(SELFTEST_STEPS) * TICKS_PER_STEP
        run.done = 0

    try:
        for index, step in enumerate(SELFTEST_STEPS):
            _update(run_id, step=step, message=f"Checking {step}")
            _CHECKS[step]()
            for tick in range(TICKS_PER_STEP):
                time.sleep(TICK_SECONDS)
                _update(run_id, done=index * TICKS_PER_STEP + tick + 1)
    except _Cancelled:
        _finish(run_id, RunStatus.CANCELLED, message="Cancelled by user")
    except Exception as exc:
        log.exception("Self-test run %s failed", run_id)
        _finish(run_id, RunStatus.FAILED, error=str(exc), message="Self-test failed")
    else:
        _finish(run_id, RunStatus.COMPLETED, step=None, message="All checks passed")


TASKS: dict[str, Callable] = {"selftest": selftest}
