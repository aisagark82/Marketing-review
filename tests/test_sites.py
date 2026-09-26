import pytest

from brandguard.api.schemas import SiteConfig
from brandguard.core import http
from brandguard.core.models import Readiness, RunStatus
from brandguard.pipeline import preflight
from tests.fakesite import HOME, FakeSite

FAKE_SITE_CONFIG = {
    "name": "Example Pharma",
    "brand_id": 1,
    "start_urls": [HOME],
    "allowed_domains": ["www.example-pharma.com"],
}


@pytest.fixture
def fake_web(monkeypatch):
    """Route the worker's HTTP client to the fake site and skip the polite waits."""
    site = FakeSite()
    monkeypatch.setattr(http, "make_http_client", lambda agent, timeout=20: site.client(agent))
    monkeypatch.setattr(preflight.time, "sleep", lambda _seconds: None)
    return site


def pfizer(client) -> dict:
    return client.get("/api/sites").json()[0]


def edit(site: dict, **changes) -> dict:
    """The site's editable settings (as the UI sends them) with some changed."""
    return {name: site[name] for name in SiteConfig.model_fields} | changes


def test_fresh_install_has_pfizer_brand_and_site(client):
    assert client.get("/api/brands").json() == [{"id": 1, "name": "Pfizer"}]
    site = pfizer(client)
    assert site["name"] == "pfizer.com"
    assert site["brand_name"] == "Pfizer"
    assert site["start_urls"] == ["https://www.pfizer.com/"]
    assert site["allowed_domains"] == ["www.pfizer.com"]
    assert site["independent"] is True
    assert site["request_interval_s"] == 2.0
    assert site["readiness"] == Readiness.NEEDS_PREFLIGHT


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"request_interval_s": 0.5}, "at least 1 s between requests"),
        ({"respect_robots": False}, "must respect robots.txt"),
        ({"start_urls": ["https://cdn.pfizer.com/"]}, "must be on an allowed domain"),
        ({"start_urls": ["ftp://www.pfizer.com/"]}, "not an http(s) URL"),
        ({"allowed_domains": ["https://www.pfizer.com"]}, "not a host name"),
        ({"exclude_patterns": ["(unclosed"]}, "invalid regular expression"),
        ({"start_urls": []}, "at least 1 item"),
        ({"max_pages": 0}, "greater than or equal to 1"),
    ],
)
def test_invalid_site_settings_are_rejected(client, changes, message):
    response = client.put("/api/sites/1", json=edit(pfizer(client), **changes))
    assert response.status_code == 422
    assert message in response.text


def test_owned_site_may_relax_the_independent_policy(client):
    changes = {"independent": False, "respect_robots": False, "request_interval_s": 0.5}
    response = client.put("/api/sites/1", json=edit(pfizer(client), **changes))
    assert response.status_code == 200
    assert response.json()["respect_robots"] is False


def test_settings_are_normalized(client):
    changes = {
        "allowed_domains": [" WWW.Pfizer.com. ", "www.pfizer.com"],
        "exclude_patterns": ["  ", r"\?page="],
    }
    site = client.put("/api/sites/1", json=edit(pfizer(client), **changes)).json()
    assert site["allowed_domains"] == ["www.pfizer.com"]
    assert site["exclude_patterns"] == [r"\?page="]


def test_unknown_brand_and_site(client):
    assert client.put("/api/sites/1", json=edit(pfizer(client), brand_id=99)).status_code == 422
    assert client.get("/api/sites/99").status_code == 404
    assert client.post("/api/sites/99/preflight").status_code == 404


def test_create_site(client):
    response = client.post("/api/sites", json=FAKE_SITE_CONFIG)
    assert response.status_code == 201
    site = response.json()
    assert site["request_interval_s"] == 2.0  # conservative defaults apply
    assert site["readiness"] == Readiness.NEEDS_PREFLIGHT
    assert len(client.get("/api/sites").json()) == 2


def test_acknowledge_requires_a_preflight_check(client):
    response = client.post(
        "/api/sites/1/preflight/acknowledge", json={"reviewed_robots_and_terms": True}
    )
    assert response.status_code == 409
    assert "Run the pre-flight check first" in response.text


def test_full_preflight_flow(client, immediate_queue, fake_web):
    site_id = client.post("/api/sites", json=FAKE_SITE_CONFIG).json()["id"]

    run = client.post(f"/api/sites/{site_id}/preflight").json()
    assert run["status"] == RunStatus.COMPLETED
    assert run["site_name"] == "Example Pharma"
    assert run["message"].startswith("No blockers found")
    assert all(agent.startswith("BrandGuard/") for agent in fake_web.user_agents)

    site = client.get(f"/api/sites/{site_id}").json()
    assert site["readiness"] == Readiness.NEEDS_ACK
    assert site["preflight_result"]["can_crawl"] is True
    assert site["preflight_result"]["effective_interval_s"] == 5

    assert (
        client.post(
            f"/api/sites/{site_id}/preflight/acknowledge", json={"reviewed_robots_and_terms": False}
        ).status_code
        == 422
    )
    acked = client.post(
        f"/api/sites/{site_id}/preflight/acknowledge", json={"reviewed_robots_and_terms": True}
    ).json()
    assert acked["readiness"] == Readiness.READY
    assert acked["preflight_acknowledged_at"] is not None

    # A cosmetic change keeps the site ready ...
    renamed = client.put(f"/api/sites/{site_id}", json=edit(acked, name="Example Pharma (US)"))
    assert renamed.json()["readiness"] == Readiness.READY
    # ... but changing what the check covered makes it stale and withdraws the acknowledgement.
    widened = client.put(
        f"/api/sites/{site_id}",
        json=edit(acked, allowed_domains=["www.example-pharma.com", "example-pharma.com"]),
    ).json()
    assert widened["readiness"] == Readiness.STALE
    assert widened["preflight_acknowledged_at"] is None
    stale_ack = client.post(
        f"/api/sites/{site_id}/preflight/acknowledge", json={"reviewed_robots_and_terms": True}
    )
    assert stale_ack.status_code == 409


def test_blocked_site_cannot_be_acknowledged(client, immediate_queue, fake_web):
    fake_web.routes[HOME] = (403, {"server": "AkamaiGHost"}, b"Access Denied")
    site_id = client.post("/api/sites", json=FAKE_SITE_CONFIG).json()["id"]
    client.post(f"/api/sites/{site_id}/preflight")

    site = client.get(f"/api/sites/{site_id}").json()
    assert site["readiness"] == Readiness.BLOCKED
    response = client.post(
        f"/api/sites/{site_id}/preflight/acknowledge", json={"reviewed_robots_and_terms": True}
    )
    assert response.status_code == 409


def test_only_one_preflight_at_a_time(client):
    first = client.post("/api/sites/1/preflight")
    assert first.status_code == 201
    assert first.json()["status"] == RunStatus.QUEUED  # no worker in this test
    assert client.post("/api/sites/1/preflight").status_code == 409


def test_runs_list_shows_site_name(client):
    client.post("/api/sites/1/preflight")
    run = client.get("/api/runs").json()[0]
    assert (run["kind"], run["site_id"], run["site_name"]) == ("preflight", 1, "pfizer.com")
