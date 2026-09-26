"""Worker process: consumes the queue and reports a heartbeat.

Huey runs with thread workers because fork-based process workers don't work
on Windows. CPU-heavy steps (OCR, Docling, Whisper) will use a spawn-based
process pool from inside the tasks in later steps.
"""

import logging
import os
import threading
from datetime import datetime

from sqlalchemy import select

from brandguard.core.db import session_scope, utcnow
from brandguard.core.models import Run, RunStatus, Setting
from brandguard.jobs.queue import get_queue

log = logging.getLogger(__name__)

HEARTBEAT_KEY = "worker.heartbeat"
HEARTBEAT_SECONDS = 5
HEARTBEAT_STALE_SECONDS = 15


def write_heartbeat() -> None:
    value = {"at": utcnow().isoformat(), "pid": os.getpid()}
    with session_scope() as session:
        row = session.get(Setting, HEARTBEAT_KEY)
        if row is None:
            session.add(Setting(key=HEARTBEAT_KEY, value=value))
        else:
            row.value = value


def read_worker_status() -> dict:
    with session_scope() as session:
        row = session.get(Setting, HEARTBEAT_KEY)
        if row is None:
            return {"online": False, "last_seen": None, "pid": None}
        last_seen = datetime.fromisoformat(row.value["at"])
    age = (utcnow() - last_seen).total_seconds()
    return {
        "online": age < HEARTBEAT_STALE_SECONDS,
        "last_seen": last_seen.isoformat(),
        "pid": row.value.get("pid"),
    }


def mark_interrupted_runs() -> int:
    """Runs left 'running' by a previous worker that stopped (sleep, crash, Ctrl+C)."""
    with session_scope() as session:
        runs = session.scalars(select(Run).where(Run.status == RunStatus.RUNNING)).all()
        for run in runs:
            run.status = RunStatus.INTERRUPTED
            run.finished_at = utcnow()
            run.message = "Worker stopped while this run was in progress"
        return len(runs)


def _heartbeat_loop(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            write_heartbeat()
        except Exception:
            log.exception("Could not write worker heartbeat")
        stop.wait(HEARTBEAT_SECONDS)


def run_worker(threads: int) -> None:
    queue = get_queue()
    interrupted = mark_interrupted_runs()
    if interrupted:
        log.warning("Marked %d unfinished run(s) as interrupted", interrupted)

    stop = threading.Event()
    heartbeat = threading.Thread(target=_heartbeat_loop, args=(stop,), daemon=True)
    heartbeat.start()
    try:
        consumer = queue.huey.create_consumer(workers=threads, worker_type="thread")
        consumer.run()
    finally:
        stop.set()
