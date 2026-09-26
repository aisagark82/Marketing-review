import json

from brandguard.core.db import session_scope
from tests.pdfs import make_pdf


def rule(client) -> dict:
    [only] = client.get("/api/brands/1/rules").json()
    return only


def test_pfizer_rule_is_seeded(client):
    r = rule(client)
    assert (r["key"], r["type"], r["severity"], r["version"]) == (
        "BRAND-NAME-001",
        "brand_name",
        "high",
        1,
    )
    assert r["config"]["allowed_casings"] == ["Pfizer", "PFIZER"]
    assert "ファイザー" in r["config"]["locales"]["ja"]["approved"]


def test_saving_creates_a_new_version(client):
    r = rule(client)
    config = r["config"] | {"disallowed": [*r["config"]["disallowed"], "Pfyzer"]}
    saved = client.put(
        f"/api/rules/{r['id']}",
        json={
            "name": r["name"],
            "severity": "medium",
            "enabled": True,
            "config": config,
        },
    ).json()
    assert saved["version"] == 2
    assert saved["severity"] == "medium"
    versions = client.get(f"/api/rules/{r['id']}/versions").json()
    assert [v["version"] for v in versions] == [2, 1]
    assert "Pfyzer" not in versions[1]["config"]["disallowed"]


def test_invalid_config_is_rejected_with_the_reason(client):
    r = rule(client)
    config = r["config"] | {"allowed_casings": ["Pfizer", "Pfiser"]}
    response = client.put(
        f"/api/rules/{r['id']}",
        json={
            "name": r["name"],
            "severity": "high",
            "enabled": True,
            "config": config,
        },
    )
    assert response.status_code == 422
    assert "spell the name exactly" in response.text
    assert rule(client)["version"] == 1  # nothing saved


def test_yaml_export(client):
    response = client.get("/api/brands/1/rules.yaml")
    assert response.headers["content-type"].startswith("application/yaml")
    assert "canonical: Pfizer" in response.text
    assert "ファイザー" in response.text  # readable, not escaped


def test_sandbox_with_saved_rule(client):
    result = client.post(
        f"/api/rules/{rule(client)['id']}/test",
        json={
            "text": "At pfizer we work with Phizer and Pfizer.",
            "language": "en",
        },
    ).json()
    assert result["matches"] == 2
    matches = result["segments"][0]["matches"]
    assert [(m["kind"], m["matched"], m["start"], m["end"]) for m in matches] == [
        ("casing", "pfizer", 3, 9),
        ("disallowed", "Phizer", 23, 29),
    ]
    assert matches[0]["context"] == "At pfizer we work with Phizer and Pfizer."


def test_sandbox_with_unsaved_settings(client):
    r = rule(client)
    unsaved = r["config"] | {"allowed_casings": ["Pfizer"]}  # try: no all caps
    result = client.post(f"/api/rules/{r['id']}/test", json={"text": "PFIZER", "config": unsaved})
    assert result.json()["matches"] == 1
    bad = client.post(
        f"/api/rules/{r['id']}/test",
        json={
            "text": "x",
            "config": r["config"] | {"canonical": ""},
        },
    )
    assert bad.status_code == 422


def test_sandbox_with_a_pdf(client):
    pdf = make_pdf(
        [["All fine: Pfizer"], ["Oops: pfizer and Pfzier"]], title="Phizer report", image_page=True
    )
    r = rule(client)
    result = client.post(
        f"/api/rules/{r['id']}/test-file",
        files={"file": ("report.pdf", pdf, "application/pdf")},
        data={"config": json.dumps(r["config"])},
    ).json()
    found = [
        (s["source"], s["page"], m["kind"], m["matched"])
        for s in result["segments"]
        for m in s["matches"]
    ]
    assert found == [
        ("pdf_meta:title", None, "disallowed", "Phizer"),
        ("pdf_text", 2, "casing", "pfizer"),
        ("pdf_text", 2, "near_miss", "Pfzier"),
    ]
    assert result["notes"] == ["Pages without a text layer (need OCR, not checked yet): 3"]


def test_sandbox_rejects_non_pdf(client):
    response = client.post(
        f"/api/rules/{rule(client)['id']}/test-file",
        files={"file": ("x.pdf", b"hello", "application/pdf")},
    )
    assert response.status_code == 422


def test_existing_database_gets_the_rule(client):
    # seed_rules is idempotent: running it again adds nothing
    from brandguard.rules.service import seed_rules

    with session_scope() as session:
        seed_rules(session)
    assert len(client.get("/api/brands/1/rules").json()) == 1


def test_missing_rule(client):
    assert client.get("/api/rules/99").status_code == 404
    assert client.post("/api/rules/99/test", json={"text": "x"}).status_code == 404


def test_reevaluate_requires_a_finished_crawl(client):
    assert client.post("/api/runs/99/evaluate").status_code == 404
