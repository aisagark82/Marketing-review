import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, status
from google.genai import errors
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from brandguard.ai.config import (
    AISettings,
    AISettingsUpdate,
    delete_api_key,
    key_status,
    load_ai_settings,
    save_ai_settings,
    save_api_key,
)
from brandguard.ai.judge import review_findings
from brandguard.ai.llm import AILimitReached, AIResponseError, AIUnavailable, open_gemini
from brandguard.api.deps import SessionDep
from brandguard.core.models import AICall, Finding, FindingStatus
from brandguard.pipeline.evaluate import summarize_findings

router = APIRouter(prefix="/ai", tags=["ai"])

USAGE_DAYS = 30
TEST_PROMPT = (
    'Reply with JSON {"lines": [...]} holding exactly these three lines: '
    '"Pfizer", "ファイザー", "辉瑞".'
)


class KeyIn(BaseModel):
    api_key: str = Field(min_length=20, max_length=200)


class TestLines(BaseModel):
    lines: list[str]


def _gemini(session):
    gemini = open_gemini(session)
    if gemini is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Add a Gemini API key first")
    return gemini


def _ai_error(exc: Exception) -> HTTPException:
    if isinstance(exc, errors.APIError):
        return HTTPException(status.HTTP_502_BAD_GATEWAY, f"Gemini error {exc.code}: {exc.message}")
    return HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


@router.get("/settings")
def read_settings(session: SessionDep) -> dict:
    return {"settings": load_ai_settings(session), "key": key_status(session)}


@router.put("/settings", response_model=AISettings)
def update_settings(update: AISettingsUpdate, session: SessionDep) -> AISettings:
    return save_ai_settings(session, update)


@router.put("/key")
def set_key(body: KeyIn, session: SessionDep) -> dict:
    save_api_key(session, body.api_key.strip())
    return key_status(session)


@router.delete("/key")
def remove_key(session: SessionDep) -> dict:
    delete_api_key(session)
    return key_status(session)


@router.get("/models")
def models(session: SessionDep) -> list[str]:
    try:
        return _gemini(session).list_models()
    except (errors.APIError, AIUnavailable) as exc:
        raise _ai_error(exc) from exc


@router.post("/test")
def test_connection(session: SessionDep) -> dict:
    """A tiny round trip in English, Japanese and Chinese: key, model and JSON all work."""
    gemini = _gemini(session)
    started = time.monotonic()
    try:
        result = gemini.generate_json(
            "test",
            "You follow instructions exactly.",
            [TEST_PROMPT],
            TestLines,
            max_output_tokens=100,
            use_cache=False,
        )
    except (errors.APIError, AIUnavailable, AILimitReached, AIResponseError) as exc:
        raise _ai_error(exc) from exc
    return {
        "model": gemini.model,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "lines": result.data.lines,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "ok": result.data.lines == ["Pfizer", "ファイザー", "辉瑞"],
    }


@router.get("/usage")
def usage(session: SessionDep) -> dict:
    settings = load_ai_settings(session)

    def cost(input_tokens: int, output_tokens: int) -> float:
        return round(
            input_tokens / 1e6 * settings.price_input_per_million
            + output_tokens / 1e6 * settings.price_output_per_million,
            4,
        )

    since = datetime.now(UTC) - timedelta(days=USAGE_DAYS)
    day = func.date(AICall.created_at)
    rows = session.execute(
        select(
            day,
            AICall.stage,
            func.count(),
            func.sum(AICall.input_tokens),
            func.sum(AICall.output_tokens),
            func.sum(func.iif(AICall.ok, 0, 1)),
        )
        .where(AICall.created_at >= since)
        .group_by(day, AICall.stage)
        .order_by(day.desc())
    ).all()
    days: dict[str, dict] = {}
    for date, stage, calls, input_tokens, output_tokens, failed in rows:
        entry = days.setdefault(
            date,
            {
                "date": date,
                "calls": 0,
                "failed": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "stages": {},
            },
        )
        entry["calls"] += calls
        entry["failed"] += failed or 0
        entry["input_tokens"] += input_tokens or 0
        entry["output_tokens"] += output_tokens or 0
        entry["stages"][stage] = calls
    for entry in days.values():
        entry["cost"] = cost(entry["input_tokens"], entry["output_tokens"])
    today = days.get(datetime.now(UTC).date().isoformat(), {"calls": 0})
    return {
        "days": list(days.values()),
        "today_calls": today["calls"],
        "daily_limit": settings.daily_request_limit,
        "total_cost": round(sum(d["cost"] for d in days.values()), 4),
        "currency": "USD",
    }


@router.post("/findings/{finding_id}/review")
def review_one(finding_id: int, session: SessionDep) -> dict:
    """Ask Gemini about one finding now (from the evidence view)."""
    finding = session.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Finding {finding_id} not found")
    if finding.status != FindingStatus.AMBIGUOUS:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only findings marked 'to review' are sent to Gemini"
        )
    gemini = _gemini(session)
    run_id = finding.run_id
    session.commit()  # the review writes in its own sessions
    try:
        outcome = review_findings(gemini, run_id, finding_ids=[finding_id])
    except (errors.APIError, AIUnavailable, AILimitReached, AIResponseError) as exc:
        raise _ai_error(exc) from exc
    session.expire_all()
    finding = session.get(Finding, finding_id)
    _refresh_run_counts(session, run_id)
    return {
        "outcome": outcome,
        "status": finding.status,
        "ai_verdict": finding.ai_verdict,
        "ai_reason": finding.ai_reason,
        "ai_suggestion": finding.ai_suggestion,
    }


def _refresh_run_counts(session, run_id: int) -> None:
    from brandguard.core.models import Run

    run = session.get(Run, run_id)
    stats = dict(run.stats or {})
    stats["findings"] = stats.get("findings", {}) | summarize_findings(run_id)
    run.stats = stats
