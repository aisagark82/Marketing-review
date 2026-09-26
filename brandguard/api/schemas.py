import re
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RunCreate(BaseModel):
    kind: Literal["selftest"] = "selftest"


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    site_id: int | None
    site_name: str | None
    status: str
    step: str | None
    done: int
    total: int
    message: str | None
    error: str | None
    cancel_requested: bool
    params: dict | None
    stats: dict | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class WorkerStatus(BaseModel):
    online: bool
    last_seen: datetime | None
    pid: int | None


class SystemInfo(BaseModel):
    version: str
    python: str
    platform: str
    home: str
    data_dir: str
    db_file: str
    worker: WorkerStatus


HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
MIN_INDEPENDENT_INTERVAL_S = 1.0


class SiteConfig(BaseModel):
    """Editable site settings. Independent tests are held to the stricter policy of design §8.1."""

    name: str = Field(min_length=1, max_length=100)
    brand_id: int
    start_urls: list[str] = Field(min_length=1, max_length=20)
    allowed_domains: list[str] = Field(min_length=1, max_length=20)
    use_sitemap: bool = True
    include_patterns: list[str] = []
    exclude_patterns: list[str] = []
    max_pages: int = Field(500, ge=1, le=100_000)
    render_js: Literal["auto", "always", "never"] = "auto"
    expand_interactive: bool = True
    independent: bool = True
    request_interval_s: float = Field(2.0, ge=0.5, le=60)
    respect_robots: bool = True
    stop_on_blocks: bool = True

    @field_validator("start_urls")
    @classmethod
    def _valid_urls(cls, urls: list[str]) -> list[str]:
        cleaned = []
        for url in (u.strip() for u in urls):
            parts = urlsplit(url)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                raise ValueError(f"not an http(s) URL: {url!r}")
            cleaned.append(url)
        return cleaned

    @field_validator("allowed_domains")
    @classmethod
    def _valid_domains(cls, domains: list[str]) -> list[str]:
        cleaned = [d.strip().lower().rstrip(".") for d in domains]
        for domain in cleaned:
            if not HOSTNAME.match(domain):
                raise ValueError(f"not a host name: {domain!r} (use e.g. www.example.com)")
        return list(dict.fromkeys(cleaned))

    @field_validator("include_patterns", "exclude_patterns")
    @classmethod
    def _valid_patterns(cls, patterns: list[str]) -> list[str]:
        cleaned = [p.strip() for p in patterns if p.strip()]
        for pattern in cleaned:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid regular expression {pattern!r}: {exc}") from exc
        return cleaned

    @model_validator(mode="after")
    def _policy(self) -> "SiteConfig":
        outside = [
            u
            for u in self.start_urls
            if (urlsplit(u).hostname or "").lower() not in self.allowed_domains
        ]
        if outside:
            raise ValueError("start URLs must be on an allowed domain: " + ", ".join(outside))
        if self.independent:
            if not self.respect_robots:
                raise ValueError("an independent test must respect robots.txt")
            if self.request_interval_s < MIN_INDEPENDENT_INTERVAL_S:
                raise ValueError(
                    "an independent test must wait at least "
                    f"{MIN_INDEPENDENT_INTERVAL_S:g} s between requests"
                )
        return self


class SiteOut(SiteConfig):
    model_config = ConfigDict(from_attributes=True)

    id: int
    brand_name: str
    readiness: str
    preflight_result: dict | None
    preflight_at: datetime | None
    preflight_acknowledged_at: datetime | None
    updated_at: datetime


class BrandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class Acknowledgement(BaseModel):
    reviewed_robots_and_terms: Literal[True]


class CrawlStart(BaseModel):
    crawler: Literal["crawlee", "crawl4ai"]


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    url: str
    final_url: str | None
    kind: str
    status: str
    status_reason: str | None
    found_on_id: int | None
    http_status: int | None
    title: str | None
    language: str | None
    screenshot_path: str | None
    file_path: str | None
    info: dict | None
    fetched_at: datetime | None
    findings: int = 0


class AssetPage(BaseModel):
    total: int
    items: list[AssetOut]


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    text: str
    text_source: str
    visibility: str
    render_transform: str | None
    locator: dict | None
    findings: list["FindingBrief"] = []


class AssetDetail(AssetOut):
    segments: list[SegmentOut]
    files: list[AssetOut]  # files and links found on this page


Severity = Literal["high", "medium", "low"]


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    brand_id: int
    key: str
    name: str
    type: str
    severity: str
    enabled: bool
    version: int
    config: dict
    updated_at: datetime


class RuleUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    severity: Severity
    enabled: bool
    config: dict


class RuleVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    severity: str
    enabled: bool
    config: dict
    created_at: datetime


class RuleTest(BaseModel):
    text: str = Field(max_length=200_000)
    language: str | None = None
    config: dict | None = None  # unsaved settings from the form; the saved rule if omitted
    severity: Severity | None = None


class MatchOut(BaseModel):
    kind: str
    start: int
    end: int
    matched: str
    expected: str
    status: str
    severity: str
    confidence: float
    note: str
    context: str | None = None


class TestedSegment(BaseModel):
    text: str
    source: str
    page: int | None = None
    matches: list[MatchOut]


class RuleTestResult(BaseModel):
    segments_checked: int
    matches: int
    segments: list[TestedSegment]  # only those with matches (or the pasted text)
    notes: list[str] = []


class FindingBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    status: str
    severity: str
    matched_text: str
    expected: str | None
    start: int
    end: int
    note: str | None
    rule_version: int


SegmentOut.model_rebuild()
AssetDetail.model_rebuild()
