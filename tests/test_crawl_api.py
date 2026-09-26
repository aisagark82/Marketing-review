import pytest

from brandguard.core.db import session_scope, utcnow
from brandguard.core.models import Readiness, RunStatus, Site
from tests.localsite import LocalSite
from tests.test_crawl import needs_chromium  # noqa: F401  (skips without a browser)


def make_ready(site_id: int, **changes) -> None:
    """Mark a site as pre-flight checked and acknowledged (the check itself is tested elsewhere)."""
    with session_scope() as session:
        site = session.get(Site, site_id)
        for name, value in changes.items():
            setattr(site, name, value)
        site.preflight_result = {"can_crawl": True}
        site.preflight_fingerprint = site.fingerprint()
        site.preflight_acknowledged_at = utcnow()
        assert site.readiness == Readiness.READY


def test_crawl_requires_a_ready_site(client):
    response = client.post("/api/sites/1/crawl", json={"crawler": "crawlee"})
    assert response.status_code == 409
    assert "pre-flight" in response.text


def test_unknown_crawler_rejected(client):
    make_ready(1)
    assert client.post("/api/sites/1/crawl", json={"crawler": "wget"}).status_code == 422


def test_one_run_per_site_at_a_time(client):
    make_ready(1)
    first = client.post("/api/sites/1/crawl", json={"crawler": "crawlee"})
    assert first.json()["status"] == RunStatus.QUEUED  # no worker in this test
    assert client.post("/api/sites/1/crawl", json={"crawler": "crawl4ai"}).status_code == 409


@pytest.mark.parametrize("crawler", ["crawlee", "crawl4ai"])
def test_crawl_through_the_api(client, immediate_queue, crawler):
    with LocalSite() as local:
        make_ready(
            1,
            start_urls=[f"{local.origin}/"],
            allowed_domains=["127.0.0.1"],
            request_interval_s=0,
            max_pages=10,
        )
        run = client.post("/api/sites/1/crawl", json={"crawler": crawler}).json()

    assert run["status"] == RunStatus.COMPLETED
    assert run["params"] == {"crawler": crawler}
    assert run["stats"]["pages"]["ok"] == 3
    assert run["message"].startswith("3 pages and 1 PDFs read")

    # Both "Phizer"s were found: hidden text on the home page, and inside the PDF.
    findings = run["stats"]["findings"]
    assert findings["violations"] == 2
    assert findings["by_kind"] == {"disallowed": 2}
    assert findings["by_asset_kind"] == {"page": 1, "pdf": 1}
    assert findings["by_visibility"] == {"hidden": 1, "visible": 1}
    assert findings["top_matches"] == [["Phizer", 2]]
    assert findings["rules"] == [{"id": 1, "key": "BRAND-NAME-001", "version": 1}]

    pages = client.get(f"/api/runs/{run['id']}/assets", params={"kind": "page", "status": "ok"})
    assert pages.json()["total"] == 3
    attempted = client.get(
        f"/api/runs/{run['id']}/assets", params={"kind": "page", "status": "ok,failed,blocked"}
    )
    assert attempted.json()["total"] == 4, [
        (a["url"], a["status"]) for a in attempted.json()["items"]
    ]  # plus the 404
    home = next(a for a in pages.json()["items"] if a["title"] == "Home | Example Pharma")

    detail = client.get(f"/api/assets/{home['id']}").json()
    assert {f["kind"] for f in detail["files"]} == {"pdf", "image"}
    hidden = client.get(f"/api/assets/{home['id']}", params={"visibility": "hidden"}).json()
    assert [s["text"] for s in hidden["segments"]] == ["Hidden campaign for Phizer"]
    [finding] = hidden["segments"][0]["findings"]
    assert (finding["kind"], finding["matched_text"], finding["start"]) == (
        "disallowed",
        "Phizer",
        20,
    )
    assert home["findings"] == 1

    pdf = client.get(f"/api/runs/{run['id']}/assets", params={"kind": "pdf"}).json()["items"][0]
    pdf_detail = client.get(f"/api/assets/{pdf['id']}").json()
    line = next(s for s in pdf_detail["segments"] if s["findings"])
    assert line["locator"]["page"] == 1 and line["text"] == "At Phizer we believe in science."

    # Change the rule, then re-evaluate the same crawl without crawling again.
    rule = client.get("/api/brands/1/rules").json()[0]
    config = rule["config"] | {
        "disallowed": [d for d in rule["config"]["disallowed"] if d != "Phizer"]
    }
    client.put(
        f"/api/rules/{rule['id']}",
        json={
            "name": rule["name"],
            "severity": "high",
            "enabled": True,
            "config": config,
        },
    )
    again = client.post(f"/api/runs/{run['id']}/evaluate").json()
    assert again["status"] == RunStatus.COMPLETED
    assert again["stats"]["findings"]["by_kind"] == {"near_miss": 2}  # now only a near-miss
    updated = client.get(f"/api/runs/{run['id']}").json()
    assert updated["stats"]["findings"]["ambiguous"] == 2
    assert updated["stats"]["findings"]["rules"][0]["version"] == 2

    screenshot = client.get(f"/files/{home['screenshot_path']}")
    assert screenshot.status_code == 200
    assert screenshot.content[:2] == b"\xff\xd8"


def test_missing_run_and_asset(client):
    assert client.get("/api/runs/99/assets").status_code == 404
    assert client.get("/api/assets/99").status_code == 404
