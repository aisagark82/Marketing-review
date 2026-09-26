"""Background tasks.

- selftest: proves the loop UI -> API -> queue -> worker -> database -> live progress
- preflight: robots.txt / start page / sitemap / terms check for a site (design §8.1)
- crawl: crawl a ready site with Crawlee or Crawl4AI, extracting text segments

Extract (files) and evaluate (rules) tasks are added in later steps.
"""

import logging
import time
import uuid
from collections.abc import Callable

from sqlalchemy import text

from brandguard.core import http
from brandguard.core.db import session_scope, utcnow
from brandguard.core.models import Run, RunStatus, Site
from brandguard.core.paths import get_paths
from brandguard.core.settings import load_settings
from brandguard.pipeline.preflight import STEPS as PREFLIGHT_STEPS
from brandguard.pipeline.preflight import PreflightConfig, run_preflight

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


def _start(run_id: int, total: int) -> bool:
    """Mark the run as running; False if it no longer exists or was cancelled while queued."""
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None or run.status in RunStatus.TERMINAL:
            return False
        run.status = RunStatus.RUNNING
        run.started_at = utcnow()
        run.total = total
        run.done = 0
        return True


def selftest(run_id: int) -> None:
    if not _start(run_id, len(SELFTEST_STEPS) * TICKS_PER_STEP):
        return

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


def preflight(run_id: int) -> None:
    with session_scope() as session:
        run = session.get(Run, run_id)
        site = run.site if run else None
        if site is None:
            return
        contact = load_settings(session).crawler_contact_email
        config = PreflightConfig(
            start_urls=list(site.start_urls),
            allowed_domains=list(site.allowed_domains),
            use_sitemap=site.use_sitemap,
            respect_robots=site.respect_robots,
            request_interval_s=site.request_interval_s,
            user_agent=http.user_agent(site.independent, contact),
        )
        site_id = site.id
        fingerprint = site.fingerprint()
    if not _start(run_id, len(PREFLIGHT_STEPS)):
        return

    def progress(step: str, done: int, total: int) -> None:
        _update(run_id, step=step, done=done, total=total, message=f"Checking {step}")

    try:
        with http.make_http_client(config.user_agent) as client:
            result = run_preflight(config, client, progress=progress)
    except _Cancelled:
        _finish(run_id, RunStatus.CANCELLED, message="Cancelled by user")
        return
    except Exception as exc:
        log.exception("Pre-flight run %s failed", run_id)
        _finish(run_id, RunStatus.FAILED, error=str(exc), message="Pre-flight check failed")
        return

    with session_scope() as session:
        site = session.get(Site, site_id)
        site.preflight_result = result
        site.preflight_at = utcnow()
        # Checked against the config as it was when the check started; if the user edited
        # the site meanwhile, the result shows as stale.
        site.preflight_fingerprint = fingerprint
        site.preflight_acknowledged_at = None
    _finish(run_id, RunStatus.COMPLETED, step=None, message=result["summary"])


def crawl(run_id: int) -> None:
    # Imported here: the crawler libraries are heavy and only the worker needs them.
    from brandguard.pipeline.crawl.discovery import RobotsUnavailable
    from brandguard.pipeline.crawl.runner import CrawlConfig, execute_crawl

    with session_scope() as session:
        run = session.get(Run, run_id)
        site = run.site if run else None
        if site is None:
            return
        contact = load_settings(session).crawler_contact_email
        config = CrawlConfig(
            run_id=run_id,
            site_id=site.id,
            crawler=run.params["crawler"],
            start_urls=list(site.start_urls),
            allowed_domains=list(site.allowed_domains),
            include_patterns=list(site.include_patterns),
            exclude_patterns=list(site.exclude_patterns),
            max_pages=site.max_pages,
            use_sitemap=site.use_sitemap,
            respect_robots=site.respect_robots,
            request_interval_s=site.request_interval_s,
            javascript=site.render_js != "never",
            expand_interactive=site.expand_interactive,
            stop_on_blocks=site.stop_on_blocks,
            user_agent=http.user_agent(site.independent, contact),
            data_dir=get_paths().data_dir,
        )
    if not _start(run_id, config.max_pages):
        return
    _update(run_id, step="discovery", message="Reading robots.txt and the sitemap")

    try:
        stats, stop_reason = execute_crawl(
            config, on_status=lambda message: _update(run_id, step="crawl", message=message)
        )
    except _Cancelled:
        _finish(run_id, RunStatus.CANCELLED, message="Cancelled by user")
        return
    except RobotsUnavailable as exc:
        _finish(
            run_id,
            RunStatus.FAILED,
            error=str(exc),
            message="robots.txt could not be read, so nothing was crawled",
        )
        return
    except Exception as exc:
        log.exception("Crawl run %s failed", run_id)
        _finish(
            run_id, RunStatus.FAILED, error=f"{type(exc).__name__}: {exc}", message="Crawl failed"
        )
        return

    pages = stats["pages"]
    summary = (
        f"{pages.get('ok', 0)} pages crawled, {sum(stats['files'].values())} files found, "
        f"{sum(stats['segments'].values())} text segments"
    )
    if stop_reason == "cancelled":
        _finish(run_id, RunStatus.CANCELLED, stats=stats, message=f"Cancelled. {summary}")
    elif stop_reason == "blocked":
        _finish(
            run_id,
            RunStatus.BLOCKED,
            stats=stats,
            message=f"Stopped: the site started refusing requests. {summary}",
        )
    else:
        _finish(run_id, RunStatus.COMPLETED, step=None, stats=stats, message=summary)


TASKS: dict[str, Callable] = {"selftest": selftest, "preflight": preflight, "crawl": crawl}
