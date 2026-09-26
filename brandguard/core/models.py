"""Database tables. Assets, segments and findings are added in later steps.

Schema changes need a matching Alembic migration in brandguard/migrations/versions/.
"""

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from brandguard.core.db import Base, UTCDateTime, utcnow


class RunStatus:
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    BLOCKED = "blocked"  # the site started refusing requests, so the crawl stopped (design §8.1)

    TERMINAL = frozenset({COMPLETED, FAILED, CANCELLED, INTERRUPTED, BLOCKED})


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
    params: Mapped[dict | None] = mapped_column(JSON)  # e.g. {"crawler": "crawlee"}
    stats: Mapped[dict | None] = mapped_column(
        JSON
    )  # crawl statistics, see pipeline/crawl/runner.py
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    site: Mapped[Site | None] = relationship(lazy="joined")

    @property
    def site_name(self) -> str | None:
        return self.site.name if self.site else None


class AssetKind:
    PAGE = "page"
    PDF = "pdf"
    OFFICE = "office"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"
    FRAME = "frame"  # an <iframe> on another host
    OTHER = "other"


class AssetStatus:
    OK = "ok"  # fetched and extracted
    FAILED = "failed"  # navigation error or HTTP error
    BLOCKED = "blocked"  # the site refused (403/429/challenge page)
    DISCOVERED = "discovered"  # a file found on a page; downloaded in a later step
    SKIPPED = "skipped"  # out of scope; status_reason says why


class Asset(Base):
    """A page or file found during a crawl run."""

    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("run_id", "url", name="uq_assets_run_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), index=True)
    status_reason: Mapped[str | None] = mapped_column(String(200))
    found_on_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"))
    http_status: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(35))  # <html lang>, as declared by the page
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    html_path: Mapped[str | None] = mapped_column(Text)  # relative to the data folder
    file_path: Mapped[str | None] = mapped_column(Text)  # downloaded file (PDF ...), same folder
    screenshot_path: Mapped[str | None] = mapped_column(Text)
    info: Mapped[dict | None] = mapped_column(JSON)  # page size, segment counts, timings
    fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Visibility:
    VISIBLE = "visible"
    HIDDEN = "hidden"
    METADATA = "metadata"
    SPOKEN = "spoken"  # speech-to-text, later steps


class Segment(Base):
    """One piece of text from an asset, with where it came from (design §4)."""

    __tablename__ = "segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    text_source: Mapped[str] = mapped_column(String(40))
    visibility: Mapped[str] = mapped_column(String(10), index=True)
    render_transform: Mapped[str | None] = mapped_column(String(20))  # CSS text-transform
    locator: Mapped[dict | None] = mapped_column(JSON)  # selector, bbox, JSON path ...
    extractor: Mapped[str] = mapped_column(String(40))


class Rule(Base):
    """A brand rule; `config` is validated by the rule type (see brandguard/rules/)."""

    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    key: Mapped[str] = mapped_column(String(50))  # e.g. BRAND-NAME-001
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10), default="high")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    config: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class RuleVersion(Base):
    """Every saved version of a rule, so each finding can say which version produced it."""

    __tablename__ = "rule_versions"
    __table_args__ = (UniqueConstraint("rule_id", "version", name="uq_rule_versions"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("rules.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(String(10))
    enabled: Mapped[bool] = mapped_column(Boolean)
    config: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class FindingStatus:
    VIOLATION = "violation"
    AMBIGUOUS = "ambiguous"  # e.g. a near-miss spelling, until Gemini (or a person) decides
    DISMISSED = "dismissed"  # reviewed: not a misspelling of the brand name


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)  # the crawl run
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    segment_id: Mapped[int] = mapped_column(
        ForeignKey("segments.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[int] = mapped_column(ForeignKey("rules.id"))
    rule_version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))  # casing, disallowed, split, near_miss, ...
    status: Mapped[str] = mapped_column(String(15))
    severity: Mapped[str] = mapped_column(String(10))
    matched_text: Mapped[str] = mapped_column(Text)
    expected: Mapped[str | None] = mapped_column(Text)
    start: Mapped[int] = mapped_column(Integer)  # character offsets in the segment text
    end: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    note: Mapped[str | None] = mapped_column(Text)
    # Gemini's review of a finding that was "to review" (verdict, reason, suggested fix).
    ai_verdict: Mapped[str | None] = mapped_column(String(20))
    ai_reason: Mapped[str | None] = mapped_column(Text)
    ai_suggestion: Mapped[str | None] = mapped_column(Text)
    ai_model: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AICall(Base):
    """One Gemini request: for the usage panel, limits and cost estimates."""

    __tablename__ = "ai_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage: Mapped[str] = mapped_column(String(30))  # judge, image_text, test
    model: Mapped[str] = mapped_column(String(80))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class AICache(Base):
    """Answers keyed by model + prompt + input, so re-evaluating a crawl costs nothing twice."""

    __tablename__ = "ai_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    stage: Mapped[str] = mapped_column(String(30))
    response: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
