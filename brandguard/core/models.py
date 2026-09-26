"""Database tables. Assets, segments and findings are added in later steps.

Schema changes need a matching Alembic migration in brandguard/migrations/versions/.
"""

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from brandguard.core.db import Base, UTCDateTime, utcnow


class RunStatus:
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"

    TERMINAL = frozenset({COMPLETED, FAILED, CANCELLED, INTERRUPTED})


class Readiness:
    """Whether a site may be crawled (design §8.1)."""

    NEEDS_PREFLIGHT = "needs_preflight"
    STALE = "stale"  # config changed since the last pre-flight check
    BLOCKED = "blocked"  # the pre-flight check found a blocker
    NEEDS_ACK = "needs_ack"  # the user hasn't confirmed reviewing robots.txt and terms
    READY = "ready"


class Setting(Base):
    """Key/value store for app settings and internal state (e.g. worker heartbeat)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Brand(Base):
    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"))
    name: Mapped[str] = mapped_column(String(100))
    start_urls: Mapped[list[str]] = mapped_column(JSON)
    allowed_domains: Mapped[list[str]] = mapped_column(JSON)
    use_sitemap: Mapped[bool] = mapped_column(Boolean, default=True)
    include_patterns: Mapped[list[str]] = mapped_column(JSON, default=list)
    exclude_patterns: Mapped[list[str]] = mapped_column(JSON, default=list)
    max_pages: Mapped[int] = mapped_column(Integer, default=500)
    render_js: Mapped[str] = mapped_column(String(10), default="auto")
    expand_interactive: Mapped[bool] = mapped_column(Boolean, default=True)
    # Politeness. An independent test (not done for the site owner) is held to
    # stricter limits: robots.txt always respected, at least 1 s between requests.
    independent: Mapped[bool] = mapped_column(Boolean, default=True)
    request_interval_s: Mapped[float] = mapped_column(Float, default=2.0)
    respect_robots: Mapped[bool] = mapped_column(Boolean, default=True)
    stop_on_blocks: Mapped[bool] = mapped_column(Boolean, default=True)
    # Latest pre-flight check and the user's acknowledgement of it.
    preflight_result: Mapped[dict | None] = mapped_column(JSON)
    preflight_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    preflight_fingerprint: Mapped[str | None] = mapped_column(String(64))
    preflight_acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    brand: Mapped[Brand] = relationship(lazy="joined")

    @property
    def brand_name(self) -> str:
        return self.brand.name

    def fingerprint(self) -> str:
        """Hash of the settings a pre-flight check depends on; a change invalidates the check."""
        relevant = {
            "start_urls": self.start_urls,
            "allowed_domains": self.allowed_domains,
            "use_sitemap": self.use_sitemap,
            "respect_robots": self.respect_robots,
        }
        return hashlib.sha256(json.dumps(relevant, sort_keys=True).encode()).hexdigest()

    @property
    def readiness(self) -> str:
        if self.preflight_result is None:
            return Readiness.NEEDS_PREFLIGHT
        if self.preflight_fingerprint != self.fingerprint():
            return Readiness.STALE
        if not self.preflight_result.get("can_crawl"):
            return Readiness.BLOCKED
        if self.preflight_acknowledged_at is None:
            return Readiness.NEEDS_ACK
        return Readiness.READY


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(50))
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.QUEUED, index=True)
    step: Mapped[str | None] = mapped_column(String(100))
    done: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    site: Mapped[Site | None] = relationship(lazy="joined")

    @property
    def site_name(self) -> str | None:
        return self.site.name if self.site else None
