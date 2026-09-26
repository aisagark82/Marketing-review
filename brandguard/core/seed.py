"""Default content for a fresh install: the Pfizer brand and its www.pfizer.com site."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from brandguard.core.models import Brand, Site


def seed_defaults(session: Session) -> None:
    from brandguard.rules.service import seed_rules

    if session.scalar(select(Brand.id).limit(1)) is None:
        _seed_pfizer(session)
    seed_rules(session)


def _seed_pfizer(session: Session) -> None:
    pfizer = Brand(name="Pfizer")
    session.add(pfizer)
    session.add(
        Site(
            brand=pfizer,
            name="pfizer.com",
            start_urls=["https://www.pfizer.com/"],
            allowed_domains=["www.pfizer.com"],
            use_sitemap=True,
            include_patterns=[],
            exclude_patterns=[],
            max_pages=500,
            render_js="auto",
            expand_interactive=True,
            independent=True,
            request_interval_s=2.0,
            respect_robots=True,
            stop_on_blocks=True,
        )
    )
