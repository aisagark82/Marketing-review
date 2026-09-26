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

from brandguard.ai.config import load_ai_settings
from brandguard.ai.images import image_text_reader
from brandguard.ai.llm import open_gemini
from brandguard.core import http
from brandguard.core.db import session_scope, utcnow
from brandguard.core.models import Run, RunStatus, Site
from brandguard.core.paths import get_paths
from brandguard.core.settings import load_settings
from brandguard.pipeline.evaluate import summarize_findings
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
        ai_settings = load_ai_settings(session)
        gemini = open_gemini(session)
        config.max_images = ai_settings.max_images_per_crawl
    read_images = (
        image_text_reader(gemini, run_id)
        if gemini is not None and ai_settings.read_images and ai_settings.max_images_per_crawl
        else None
    )
    if not _start(run_id, config.max_pages):
        return
    _update(run_id, step="discovery", message="Reading robots.txt and the sitemap")

    def cancelled() -> bool:
        with session_scope() as session:
            return session.get(Run, run_id).cancel_requested

    try:
        stats, stop_reason = execute_crawl(
            config,
            on_status=lambda message: _update(run_id, step="crawl", message=message),
            is_cancelled=cancelled,
            read_image_text=read_images,
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

    if stop_reason != "cancelled":
        _update(run_id, step="evaluate", message="Checking the text against the brand rules")
        stats["findings"] = _evaluate(run_id)
        stats["ai"] = _ai_review(run_id, run_id, gemini, ai_settings, cancelled)
        stats["ai"]["images"] = bool(read_images)
        stats["findings"] |= summarize_findings(run_id)  # after Gemini's verdicts

    summary = _crawl_summary(stats)
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


def _ai_review(crawl_run_id: int, progress_run_id: int, gemini, ai_settings, cancelled) -> dict:
    """Gemini decides the findings still "to review". Failures pause this step, not the run."""
    from brandguard.ai.judge import review_findings
    from brandguard.ai.llm import AILimitReached, AIResponseError, AIUnavailable

    if gemini is None:
        return {"enabled": False, "reason": "No Gemini API key (Settings)"}
    if not ai_settings.review_near_misses:
        return {"enabled": False, "reason": "Reviewing possible misspellings is switched off"}

    def progress(done: int, total: int) -> None:
        _update(
            progress_run_id,
            step="ai",
            message=f"Gemini is reviewing possible misspellings: {done} of {total}",
        )

    result = {"enabled": True, "model": gemini.model}
    try:
        result["review"] = review_findings(
            gemini, crawl_run_id, on_progress=progress, should_stop=cancelled
        )
    except (AILimitReached, AIUnavailable, AIResponseError) as exc:
        result["error"] = str(exc)
    except Exception as exc:  # e.g. a Gemini service error after retries
        log.exception("Gemini review failed for run %s", crawl_run_id)
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _crawl_summary(stats: dict) -> str:
    pages = stats["pages"].get("ok", 0)
    pdfs = stats.get("documents", {}).get("ok", 0)
    segments = sum(stats["segments"].values())
    text = f"{pages} pages and {pdfs} PDFs read, {segments} text segments"
    findings = stats.get("findings")
    if findings:
        text += f"; {findings['violations']} violations, {findings['ambiguous']} to review"
        if findings.get("dismissed"):
            text += f", {findings['dismissed']} dismissed by Gemini"
    if stats.get("ai", {}).get("error"):
        text += f" (Gemini: {stats['ai']['error']})"
    return text


def _evaluate(crawl_run_id: int, progress_run_id: int | None = None) -> dict:
    from brandguard.pipeline.evaluate import evaluate_run

    progress_run_id = progress_run_id or crawl_run_id

    def progress(done: int, total: int) -> None:
        _update(progress_run_id, message=f"Checking text: {done} of {total} pages and files")

    return evaluate_run(crawl_run_id, on_progress=progress)


def evaluate(run_id: int) -> None:
    """Re-check an earlier crawl with the current rules (e.g. after editing a rule)."""
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            return
        crawl_run_id = run.params["crawl_run_id"]
        ai_settings = load_ai_settings(session)
        gemini = open_gemini(session)
    if not _start(run_id, 1):
        return

    def cancelled() -> bool:
        with session_scope() as session:
            return session.get(Run, run_id).cancel_requested

    try:
        findings = _evaluate(crawl_run_id, progress_run_id=run_id)
        ai = _ai_review(crawl_run_id, run_id, gemini, ai_settings, cancelled)
        findings |= summarize_findings(crawl_run_id)
    except _Cancelled:
        _finish(run_id, RunStatus.CANCELLED, message="Cancelled by user")
        return
    except Exception as exc:
        log.exception("Evaluation run %s failed", run_id)
        _finish(
            run_id,
            RunStatus.FAILED,
            error=f"{type(exc).__name__}: {exc}",
            message="Evaluation failed",
        )
        return
    with session_scope() as session:
        crawl_run = session.get(Run, crawl_run_id)
        ai = ai | {"images": (crawl_run.stats or {}).get("ai", {}).get("images", False)}
        crawl_run.stats = (crawl_run.stats or {}) | {"findings": findings, "ai": ai}
        crawl_run.message = _crawl_summary(crawl_run.stats)
    _finish(
        run_id,
        RunStatus.COMPLETED,
        step=None,
        done=1,
        stats={"findings": findings, "ai": ai},
        message=f"{findings['violations']} violations, {findings['ambiguous']} to review "
        f"in {findings['segments_checked']} text segments",
    )


TASKS: dict[str, Callable] = {
    "selftest": selftest,
    "preflight": preflight,
    "crawl": crawl,
    "evaluate": evaluate,
}
