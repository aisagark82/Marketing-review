import httpx
import pytest

from brandguard.core.http import fetch, user_agent
from brandguard.pipeline.preflight import (
    PreflightConfig,
    relevant_robots_groups,
    run_preflight,
)
from tests.fakesite import HOME, ORIGIN, FakeSite

BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>
<urlset><url><loc>&lol2;</loc></url></urlset>"""


def config(**overrides) -> PreflightConfig:
    values = {
        "start_urls": [HOME],
        "allowed_domains": ["www.example-pharma.com"],
        "use_sitemap": True,
        "respect_robots": True,
        "request_interval_s": 2.0,
        "user_agent": "BrandGuard/test",
    }
    return PreflightConfig(**(values | overrides))


def run(site: FakeSite, **overrides) -> tuple[dict, list[float]]:
    sleeps: list[float] = []
    with site.client() as client:
        result = run_preflight(config(**overrides), client, sleep=sleeps.append)
    return result, sleeps


def check(result: dict, check_id: str) -> dict:
    return next(c for c in result["checks"] if c["id"] == check_id)


def test_happy_path_reports_everything_and_allows_crawling():
    site = FakeSite()
    result, _ = run(site)

    assert result["can_crawl"] is True
    assert all(c["status"] != "fail" for c in result["checks"])
    assert result["robots"]["crawl_delay_s"] == 5
    assert result["effective_interval_s"] == 5
    assert result["robots"]["sitemaps"] == [f"{ORIGIN}/sitemap_index.xml"]
    assert result["robots"]["start_urls_allowed"] == {HOME: True}
    # Only the `*` group applies to BrandGuard, not BadBot/OtherBot.
    assert result["robots"]["groups"] == [
        {
            "user_agents": ["*"],
            "rules": [["Disallow", "/search"], ["Allow", "/search/help"], ["Crawl-Delay", "5"]],
        }
    ]
    page = result["start_page"]
    assert page["title"] == "Example Pharma | Home"
    assert page["in_scope_links"] == 4  # /news and /news#latest count once; social link excluded
    assert result["terms_links"] == [
        {"text": "Terms of Use", "url": f"{ORIGIN}/legal/terms-of-use"}
    ]
    sitemap = result["sitemap"]
    assert [c["url"].rsplit("/", 1)[-1] for c in sitemap["checked"]] == [
        "sitemap_index.xml",
        "sitemap-pages.xml",
        "sitemap-news.xml.gz",
    ]
    assert sitemap["urls_seen"] == 8
    assert sitemap["in_scope_urls"] == 7  # the investors.* subdomain is out of scope
    assert sitemap["unchecked_sitemaps"] == 1
    assert len(sitemap["sample_urls"]) == 7


def test_requests_are_paced_by_the_longer_of_interval_and_crawl_delay():
    site = FakeSite()
    _, sleeps = run(site)
    assert len(site.requested) == 5  # robots, home page, 3 sitemap files
    assert len(sleeps) == 4
    assert all(4.5 < s <= 5 for s in sleeps)


def test_configured_interval_wins_when_longer_than_crawl_delay():
    _, sleeps = run(FakeSite(), request_interval_s=8)
    assert all(7.5 < s <= 8 for s in sleeps)


def test_specific_group_for_brandguard_overrides_star_group():
    site = FakeSite()
    site.routes[f"{ORIGIN}/robots.txt"] = (
        200,
        {},
        b"User-agent: *\nAllow: /\n\nUser-agent: brandguard\nDisallow: /\n",
    )
    result, _ = run(site)
    assert result["can_crawl"] is False
    assert check(result, "robots-start")["status"] == "fail"
    assert check(result, "start-page")["detail"].startswith("Not fetched")
    assert HOME not in site.requested


def test_missing_robots_means_no_restrictions():
    site = FakeSite()
    del site.routes[f"{ORIGIN}/robots.txt"]
    result, _ = run(site)
    assert check(result, "robots")["status"] == "info"
    assert result["can_crawl"] is True
    # Without a Sitemap line, the default location is tried (and is missing here).
    assert result["sitemap"]["checked"][0]["url"] == f"{ORIGIN}/sitemap.xml"
    assert check(result, "sitemap")["status"] == "warn"


@pytest.mark.parametrize("status", [500, 503, 401, 403])
def test_unreadable_or_blocked_robots_stops_the_check(status):
    site = FakeSite()
    site.routes[f"{ORIGIN}/robots.txt"] = (status, {}, b"")
    result, _ = run(site)
    assert result["can_crawl"] is False
    assert check(result, "robots")["status"] == "fail"
    assert site.requested == [f"{ORIGIN}/robots.txt"]


def test_robots_network_error_stops_the_check():
    site = FakeSite()
    site.routes[f"{ORIGIN}/robots.txt"] = (0, {}, httpx.ConnectError("connection refused"))
    result, _ = run(site)
    assert result["can_crawl"] is False
    assert "ConnectError" in result["robots"]["error"]


def test_bot_protection_is_detected_and_not_bypassed():
    site = FakeSite()
    site.routes[HOME] = (403, {"server": "cloudflare"}, b"<html>Just a moment...</html>")
    result, _ = run(site)
    assert result["can_crawl"] is False
    assert "Cloudflare" in result["start_page"]["bot_protection"]
    assert "does not try to get around" in check(result, "start-page")["detail"]
    assert result["summary"].startswith(
        "Crawling is not possible. Start page: Blocked by Cloudflare"
    )
    # Once the site signals it is blocking us, no further requests are made.
    assert site.requested == [f"{ORIGIN}/robots.txt", HOME]
    assert check(result, "sitemap")["detail"].startswith("Skipped")
    assert "could not be read" in check(result, "terms")["detail"]


def test_challenge_page_marker_is_detected():
    site = FakeSite()
    site.routes[HOME] = (429, {}, b"<html>Please complete the CAPTCHA</html>")
    result, _ = run(site)
    assert result["start_page"]["bot_protection"] == 'Bot-protection page (contains "captcha")'


def test_plain_error_status_fails_without_bot_label():
    site = FakeSite()
    site.routes[HOME] = (404, {}, b"")
    result, _ = run(site)
    assert result["start_page"]["bot_protection"] is None
    assert check(result, "start-page")["detail"].endswith("returned HTTP 404.")


def test_redirect_to_the_www_host_is_followed():
    result, _ = run(
        FakeSite(),
        start_urls=["https://example-pharma.com/"],
        allowed_domains=["example-pharma.com", "www.example-pharma.com"],
    )
    page = result["start_page"]
    assert page["final_url"] == HOME
    assert page["redirects"] == ["https://example-pharma.com/"]
    assert check(result, "start-page")["status"] == "ok"


def test_redirect_outside_allowed_domains_fails():
    site = FakeSite()
    site.routes[HOME] = (302, {"location": "https://elsewhere.example.org/"}, b"")
    site.routes["https://elsewhere.example.org/"] = (200, {}, b"<html></html>")
    result, _ = run(site)
    assert result["can_crawl"] is False
    assert "outside the allowed domains" in check(result, "start-page")["detail"]


def test_start_page_network_error_fails():
    site = FakeSite()
    site.routes[HOME] = (0, {}, httpx.ReadTimeout("timed out"))
    result, _ = run(site)
    assert "ReadTimeout" in check(result, "start-page")["detail"]
    assert check(result, "terms")["status"] == "warn"


def test_hostile_sitemap_xml_is_rejected_safely():
    site = FakeSite()
    site.routes[f"{ORIGIN}/sitemap_index.xml"] = (200, {}, BILLION_LAUGHS)
    result, _ = run(site)
    assert "could not parse" in result["sitemap"]["checked"][0]["error"]
    assert check(result, "sitemap")["status"] == "warn"
    assert result["can_crawl"] is True


def test_sitemap_can_be_switched_off():
    site = FakeSite()
    result, _ = run(site, use_sitemap=False)
    assert check(result, "sitemap")["status"] == "info"
    assert not any("sitemap" in url for url in site.requested)


def test_no_terms_link_asks_user_to_find_them():
    site = FakeSite()
    site.routes[HOME] = (200, {}, b"<html><a href='/about'>About</a></html>")
    result, _ = run(site)
    assert result["terms_links"] == []
    assert check(result, "terms")["status"] == "warn"


def test_progress_reports_each_step():
    steps = []
    with FakeSite().client() as client:
        run_preflight(
            config(), client, progress=lambda s, d, t: steps.append((s, d, t)), sleep=lambda _: None
        )
    assert steps == [
        ("robots.txt", 0, 4),
        ("start page", 1, 4),
        ("sitemap", 2, 4),
        ("terms of use", 3, 4),
        ("done", 4, 4),
    ]


def test_relevant_groups_handles_multi_agent_groups_and_comments():
    text = (
        "User-agent: Foo\nUser-agent: BrandGuard # us\nDisallow: /x\n\nUser-agent: *\nDisallow:\n"
    )
    assert relevant_robots_groups(text) == [
        {"user_agents": ["Foo", "BrandGuard"], "rules": [["Disallow", "/x"]]}
    ]


def test_fetch_caps_body_size():
    site = FakeSite({f"{ORIGIN}/big": (200, {}, b"x" * 1000)})
    with site.client() as client:
        fetched = fetch(client, f"{ORIGIN}/big", max_bytes=100)
    assert fetched.truncated is True
    assert len(fetched.body) == 100


def test_user_agent_is_honest_about_purpose_and_contact():
    assert "(independent brand-compliance test)" in user_agent(True)
    assert user_agent(False, "me@example.com").endswith(
        "(brand-compliance review; contact: me@example.com)"
    )
