"""Gemini reviews findings marked "to review" (near-miss spellings) and decides each one."""

import hashlib
import html
import logging
from collections import Counter
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select

from brandguard.ai.llm import Gemini
from brandguard.ai.prompts import JUDGE_SYSTEM
from brandguard.core.db import session_scope
from brandguard.core.models import AICache, Asset, Finding, FindingStatus, Rule, Segment

log = logging.getLogger(__name__)

BATCH_SIZE = 20  # candidates per request: fewer requests, still short prompts
CONTEXT_CHARS = 150
STAGE = "judge"


class Verdict(BaseModel):
    id: int
    verdict: Literal["misspelling", "not_brand", "unsure"]
    reason: str
    suggestion: str | None = None


class JudgeAnswer(BaseModel):
    verdicts: list[Verdict]


def _context(text: str, start: int, end: int) -> str:
    left, right = max(0, start - CONTEXT_CHARS), min(len(text), end + CONTEXT_CHARS)
    return ("…" if left else "") + text[left:right] + ("…" if right < len(text) else "")


def _candidate_key(model: str, canonical: str, word: str, context: str) -> str:
    raw = "\x1f".join((STAGE, model, JUDGE_SYSTEM, canonical, word, context))
    return hashlib.sha256(raw.encode()).hexdigest()


def _prompt(canonical: str, allowed: list[str], batch: list[dict]) -> str:
    items = "\n".join(
        f'<candidate id="{i}" language="{html.escape(c["language"] or "unknown")}">'
        f"<word>{html.escape(c['word'])}</word><context>{html.escape(c['context'])}</context>"
        "</candidate>"
        for i, c in enumerate(batch, start=1)
    )
    return (
        f'<brand name="{html.escape(canonical)}" allowed="{html.escape(", ".join(allowed))}"/>\n'
        f"<candidates>\n{items}\n</candidates>"
    )


def _apply(finding_id: int, verdict: Verdict, rule_severity: str, model: str) -> str:
    with session_scope() as session:
        finding = session.get(Finding, finding_id)
        finding.ai_verdict = verdict.verdict
        finding.ai_reason = verdict.reason
        finding.ai_suggestion = verdict.suggestion
        finding.ai_model = model
        if verdict.verdict == "misspelling":
            finding.status = FindingStatus.VIOLATION
            finding.severity = rule_severity  # confirmed: as serious as any other misspelling
        elif verdict.verdict == "not_brand":
            finding.status = FindingStatus.DISMISSED
    return verdict.verdict


def review_findings(
    gemini: Gemini,
    run_id: int,
    finding_ids: list[int] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    """Decide every finding still "to review" in a crawl run (or just the given ones)."""
    with session_scope() as session:
        query = (
            select(Finding, Segment.text, Asset.language, Rule)
            .join(Segment, Finding.segment_id == Segment.id)
            .join(Asset, Finding.asset_id == Asset.id)
            .join(Rule, Finding.rule_id == Rule.id)
            .where(Finding.run_id == run_id, Finding.status == FindingStatus.AMBIGUOUS)
        )
        if finding_ids is not None:
            query = query.where(Finding.id.in_(finding_ids))
        candidates = [
            {
                "finding_id": f.id,
                "word": f.matched_text,
                "language": language,
                "context": _context(text, f.start, f.end),
                "rule_id": rule.id,
                "canonical": rule.config["canonical"],
                "allowed": rule.config["allowed_casings"],
                "severity": rule.severity,
            }
            for f, text, language, rule in session.execute(query)
        ]

    outcome: Counter = Counter()
    pending: list[dict] = []
    for candidate in candidates:  # answers from earlier runs (e.g. before a re-evaluation)
        candidate["key"] = _candidate_key(
            gemini.model, candidate["canonical"], candidate["word"], candidate["context"]
        )
        with session_scope() as session:
            hit = session.get(AICache, candidate["key"])
        if hit is not None:
            outcome[
                _apply(
                    candidate["finding_id"],
                    Verdict.model_validate(hit.response),
                    candidate["severity"],
                    gemini.model,
                )
            ] += 1
            outcome["from_cache"] += 1
        else:
            pending.append(candidate)

    for rule_id in sorted({c["rule_id"] for c in pending}):
        group = [c for c in pending if c["rule_id"] == rule_id]
        for start in range(0, len(group), BATCH_SIZE):
            if should_stop and should_stop():
                outcome["not_reviewed"] += len(group) - start
                return dict(outcome)
            if on_progress:
                on_progress(start, len(group))
            batch = group[start : start + BATCH_SIZE]
            prompt = _prompt(batch[0]["canonical"], batch[0]["allowed"], batch)
            answer = gemini.generate_json(
                STAGE,
                JUDGE_SYSTEM,
                [prompt],
                JudgeAnswer,
                max_output_tokens=150 * len(batch) + 100,
                run_id=run_id,
                use_cache=False,
            ).data
            by_id = {v.id: v for v in answer.verdicts}
            for number, candidate in enumerate(batch, start=1):
                verdict = by_id.get(number)
                if verdict is None:  # left out of the answer: stays "to review"
                    outcome["unanswered"] += 1
                    continue
                verdict.id = 1
                with session_scope() as session:
                    session.merge(
                        AICache(key=candidate["key"], stage=STAGE, response=verdict.model_dump())
                    )
                outcome[
                    _apply(candidate["finding_id"], verdict, candidate["severity"], gemini.model)
                ] += 1
    return dict(outcome) | {"candidates": len(candidates)}
