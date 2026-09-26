"""Loading, saving (with version history) and exporting rules."""

import yaml
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from brandguard.core.models import Brand, Rule, RuleVersion
from brandguard.rules.brand_name import BrandNameConfig, BrandNameRule
from brandguard.rules.defaults import PFIZER_BRAND_NAME

RULE_TYPES: dict[str, type[BaseModel]] = {"brand_name": BrandNameConfig}


def validate_config(rule_type: str, config: dict) -> dict:
    return RULE_TYPES[rule_type](**config).model_dump()


def checker(rule_type: str, config: dict, severity: str) -> BrandNameRule:
    if rule_type != "brand_name":
        raise ValueError(f"unknown rule type {rule_type!r}")
    return BrandNameRule(BrandNameConfig(**config), severity)


def save_rule(
    session: Session, rule: Rule, *, name: str, severity: str, enabled: bool, config: dict
) -> Rule:
    """Validate and store a new version of the rule."""
    rule.config = validate_config(rule.type, config)
    rule.name, rule.severity, rule.enabled = name, severity, enabled
    rule.version = (rule.version or 0) + 1
    session.add(
        RuleVersion(
            rule_id=rule.id,
            version=rule.version,
            severity=severity,
            enabled=enabled,
            config=rule.config,
        )
    )
    session.flush()
    return rule


def create_rule(
    session: Session,
    brand: Brand,
    key: str,
    name: str,
    rule_type: str,
    config: dict,
    severity: str = "high",
) -> Rule:
    rule = Rule(
        brand_id=brand.id,
        key=key,
        name=name,
        type=rule_type,
        severity=severity,
        enabled=True,
        version=0,
        config={},
    )
    session.add(rule)
    session.flush()
    return save_rule(session, rule, name=name, severity=severity, enabled=True, config=config)


def seed_rules(session: Session) -> None:
    """Give the Pfizer brand its brand-name rule, once (also for databases from earlier steps)."""
    pfizer = session.scalar(select(Brand).where(Brand.name == "Pfizer"))
    if pfizer is None or session.scalar(select(Rule.id).where(Rule.brand_id == pfizer.id)):
        return
    create_rule(
        session, pfizer, "BRAND-NAME-001", "Brand name: Pfizer", "brand_name", PFIZER_BRAND_NAME
    )


def rules_yaml(rules: list[Rule], brand: Brand) -> str:
    document = {
        "brand": brand.name,
        "rules": [
            {
                "id": r.key,
                "name": r.name,
                "type": r.type,
                "severity": r.severity,
                "enabled": r.enabled,
                "version": r.version,
                **r.config,
            }
            for r in rules
        ],
    }
    return yaml.safe_dump(document, allow_unicode=True, sort_keys=False, width=100)
