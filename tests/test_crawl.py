import pytest
from sqlalchemy import select

from brandguard.core.db import session_scope
from brandguard.core.models import Asset, Run, Segment
from brandguard.core.paths import get_paths
from brandguard.pipeline.crawl.adapters import CRAWLERS
from brandguard.pipeline.crawl.runner import CrawlConfig, execute_crawl
from tests.browser import async_playwright, launch
from tests.localsite import LocalSite


@pytest.fixture(scope="module", autouse=True)
def needs_chromium():
    import asyncio

    async def check():
        async with async_playwright() as p:
            await (await launch(p)).close()

    asyncio.run(check())


@pytest.fixture
def run_id():
    with session_scope() as session:
        run = Run(kind="crawl", site_id=1, params={"crawler": "test"})
        session.add(run)
        session.flush()
        return run.id


def config(site: LocalSite, run_id: int, crawler: str, **overrides) -> CrawlConfig:
    values = dict(
        run_id=run_id,
        site_id=1,
        crawler=crawler,
        start_urls=[f"{site.origin}/"],
        allowed_domains=["127.0.0.1"],
        max_pages=20,
        request_interval_s=0,
        user_agent="BrandGuard/test (independent brand-compliance test)",
        data_dir=get_paths().data_dir,
    )
    return CrawlConfig(**(values | overrides))


def assets(run_id: int) -> dict[str, Asset]:
    with session_scope() as session:
        return {a.url: a for a in session.scalars(select(Asset).where(Asset.run_id == run_id))}


@pytest.mark.parametrize("crawler", CRAWLERS)
def test_crawl_extracts_pages_and_respects_scope(crawler, run_id):
    with LocalSite() as site:
        stats, stop_reason = execute_crawl(config(site, run_id, crawler))
        o = site.origin

    found = assets(run_id)
    assert stop_reason is None
    assert {found[f"{o}/{p}"].status for p in ["", "about", "news"]} == {"ok"}
    assert found[f"{o}/missing"].status == "failed"
    assert found[f"{o}/missing"].http_status == 404
    assert found[f"{o}/leave"].status_reason == "redirected_third_party"
    assert found[f"{o}/private/area"].status_reason == "robots"
    assert found[f"{o}/files/report.pdf"].status == "discovered"
    assert found[f"{o}/files/report.pdf"].kind == "pdf"
    assert found[f"{o}/logo.png"].kind == "image"
    assert found["https://social.example.net/pharma"].status_reason == "third_party"

    # The page's own images load as in a normal browser (they appear in screenshots) ...
    assert ("/logo.png", "BrandGuard/test (independent brand-compliance test)") in site.requests
    # ... robots.txt was honoured, and every request identified itself honestly
    assert not any(path.startswith("/private") for path, _ in site.requests)
    assert {agent for _, agent in site.requests} == {
        "BrandGuard/test (independent brand-compliance test)"
    }

    home = found[f"{o}/"]
    assert home.title == "Home | Example Pharma"
    assert home.language == "en"
    assert home.html_path and home.screenshot_path
    assert (get_paths().data_dir / home.screenshot_path).exists()
    with session_scope() as session:
        texts = {
            s.text: s.visibility
            for s in session.scalars(select(Segment).where(Segment.asset_id == home.id))
        }
    assert texts["Welcome to Example Pharma"] == "visible"
    assert texts["Our science story."] == "visible"
    assert texts["Hidden campaign for Phizer"] == "hidden"
    assert texts["Example Pharma logo"] == "metadata"

    assert stats["crawler"] == crawler
    assert stats["pages"] == {"ok": 3, "failed": 1, "redirected_out_of_scope": 1}
    assert stats["files"] == {"image": 1, "pdf": 1}
    assert stats["skipped"]["robots"] == 1
    assert stats["seeds"]["from_sitemap"] == 1  # /news; the home page was already a start URL
    assert stats["peak_rss_mb"] > 0
    assert stats["segments"]["visible"] >= 4


@pytest.mark.parametrize("crawler", CRAWLERS)
def test_page_limit_stops_the_crawl(crawler, run_id):
    with LocalSite() as site:
        stats, stop_reason = execute_crawl(config(site, run_id, crawler, max_pages=2))
    assert stop_reason == "page_limit"
    assert sum(stats["pages"].values()) == 2


@pytest.mark.parametrize("crawler", CRAWLERS)
def test_repeated_refusals_stop_the_crawl(crawler, run_id):
    with LocalSite() as site:
        o = site.origin
        paths = ["/p1", "/p2", "/p3", "/p4", "/p5"]
        site.routes["/sitemap.xml"] = (
            200,
            "application/xml",
            (
                '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                + "".join(f"<url><loc>{o}{p}</loc></url>" for p in paths)
                + "</urlset>"
            ).encode(),
        )
        for path in paths:
            site.routes[path] = (403, "text/html", b"<html>Access denied</html>")
        stats, stop_reason = execute_crawl(config(site, run_id, crawler, start_urls=[f"{o}/p1"]))
        requested = [path for path, _ in site.requests]
    assert stop_reason == "blocked"
    assert stats["pages"] == {"blocked": 3}
    assert "/p4" not in requested and "/p5" not in requested  # stopped asking


@pytest.mark.parametrize("crawler", CRAWLERS)
def test_stopped_crawl_does_not_leak_into_the_next(crawler, run_id):
    with LocalSite() as first:
        o = first.origin
        first.routes["/sitemap.xml"] = (
            200,
            "application/xml",
            (
                '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                + "".join(f"<url><loc>{o}/p{i}</loc></url>" for i in range(1, 6))
                + "</urlset>"
            ).encode(),
        )
        for i in range(1, 6):
            first.routes[f"/p{i}"] = (403, "text/html", b"<html>Access denied</html>")
        _, stop_reason = execute_crawl(config(first, run_id, crawler, start_urls=[f"{o}/p1"]))
        assert stop_reason == "blocked"

        with LocalSite() as second:
            execute_crawl(config(second, run_id, crawler))
        # The blocked site gets no further requests, and nothing from it lands in the new run.
        assert not any(path in ("/p4", "/p5") for path, _ in first.requests)
    assert not [url for url in assets(run_id) if url.startswith(o) and url.endswith(("p4", "p5"))]
