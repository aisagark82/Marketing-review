import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from brandguard.api.deps import SessionDep
from brandguard.api.schemas import (
    MatchOut,
    RuleOut,
    RuleTest,
    RuleTestResult,
    RuleUpdate,
    RuleVersionOut,
    TestedSegment,
)
from brandguard.core.models import Brand, Rule, RuleVersion
from brandguard.pipeline.extract.pdf import PdfError, extract_pdf
from brandguard.rules.service import checker, rules_yaml, save_rule, validate_config

router = APIRouter(tags=["rules"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_SEGMENTS_SHOWN = 500


def _rule_or_404(session: Session, rule_id: int) -> Rule:
    rule = session.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Rule {rule_id} not found")
    return rule


def _invalid(exc: ValidationError) -> HTTPException:
    detail = [
        {"loc": ["body", "config", *e["loc"]], "msg": e["msg"], "type": e["type"]}
        for e in exc.errors()
    ]
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)


def _checker_for(rule: Rule, config: dict | None, severity: str | None):
    try:
        cfg = validate_config(rule.type, config) if config is not None else rule.config
    except ValidationError as exc:
        raise _invalid(exc) from exc
    return checker(rule.type, cfg, severity or rule.severity)


@router.get("/brands/{brand_id}/rules", response_model=list[RuleOut])
def list_rules(brand_id: int, session: SessionDep) -> list[Rule]:
    return list(session.scalars(select(Rule).where(Rule.brand_id == brand_id).order_by(Rule.key)))


@router.get("/brands/{brand_id}/rules.yaml", response_class=PlainTextResponse)
def export_rules(brand_id: int, session: SessionDep) -> PlainTextResponse:
    brand = session.get(Brand, brand_id)
    if brand is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Brand {brand_id} not found")
    rules = session.scalars(select(Rule).where(Rule.brand_id == brand_id).order_by(Rule.key)).all()
    return PlainTextResponse(
        rules_yaml(list(rules), brand),
        media_type="application/yaml",
        headers={"Content-Disposition": f'inline; filename="{brand.name.lower()}-rules.yaml"'},
    )


@router.get("/rules/{rule_id}", response_model=RuleOut)
def read_rule(rule_id: int, session: SessionDep) -> Rule:
    return _rule_or_404(session, rule_id)


@router.put("/rules/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: int, update: RuleUpdate, session: SessionDep) -> Rule:
    rule = _rule_or_404(session, rule_id)
    try:
        return save_rule(
            session,
            rule,
            name=update.name,
            severity=update.severity,
            enabled=update.enabled,
            config=update.config,
        )
    except ValidationError as exc:
        raise _invalid(exc) from exc


@router.get("/rules/{rule_id}/versions", response_model=list[RuleVersionOut])
def rule_versions(rule_id: int, session: SessionDep) -> list[RuleVersion]:
    _rule_or_404(session, rule_id)
    query = select(RuleVersion).where(RuleVersion.rule_id == rule_id)
    return list(session.scalars(query.order_by(RuleVersion.version.desc())))


@router.post("/rules/{rule_id}/test", response_model=RuleTestResult)
def test_text(rule_id: int, test: RuleTest, session: SessionDep) -> RuleTestResult:
    """The sandbox: check pasted text, with the saved rule or unsaved settings."""
    check = _checker_for(_rule_or_404(session, rule_id), test.config, test.severity)
    matches = check.check(test.text, test.language)
    return RuleTestResult(
        segments_checked=1,
        matches=len(matches),
        segments=[
            TestedSegment(
                text=test.text,
                source="pasted",
                matches=[MatchOut(**vars(m), context=m.context(test.text)) for m in matches],
            )
        ],
    )


@router.post("/rules/{rule_id}/test-file", response_model=RuleTestResult)
async def test_file(
    rule_id: int,
    session: SessionDep,
    file: UploadFile = File(...),  # noqa: B008  (FastAPI's way to declare an upload)
    config: str | None = Form(None),  # JSON of unsaved settings
    language: str | None = Form(None),
) -> RuleTestResult:
    """The sandbox: check every piece of text in an uploaded PDF."""
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The file is larger than 50 MB")
    try:
        extraction = extract_pdf(data)
    except PdfError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    check = _checker_for(
        _rule_or_404(session, rule_id), json.loads(config) if config else None, None
    )
    shown: list[TestedSegment] = []
    total = 0
    for segment in extraction.segments:
        matches = check.check(segment["text"], language)
        total += len(matches)
        if matches and len(shown) < MAX_SEGMENTS_SHOWN:
            shown.append(
                TestedSegment(
                    text=segment["text"],
                    source=segment["source"],
                    page=(segment["locator"] or {}).get("page"),
                    matches=[MatchOut(**vars(m), context=None) for m in matches],
                )
            )
    notes = []
    if extraction.needs_ocr:
        pages = ", ".join(map(str, extraction.pages_without_text[:20]))
        notes.append(f"Pages without a text layer (need OCR, not checked yet): {pages}")
    return RuleTestResult(
        segments_checked=len(extraction.segments), matches=total, segments=shown, notes=notes
    )
