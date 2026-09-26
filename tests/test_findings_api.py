import csv
import gzip
import io

import pytest

from brandguard.core.db import session_scope, utcnow
from brandguard.core.models import Asset, Run, Segment
from brandguard.core.paths import get_paths
from brandguard.pipeline.evaluate import evaluate_run

HOME_HTML = """<html><head><title>Home</title>
<meta name="description" content="pfizer medicines">
<script type="application/ld+json">{"@type": "Organization", "name": "Phizer Inc."}</script>
</head><body><h1 id="hero">Welcome to pfizer</h1>
<div id="promo" style="display:none">Old Phizer campaign</div></body></html>"""


def make_crawl(texts: dict[str, list[tuple]], crawler="crawlee", with_pdf=True) -> int:
    """A finished crawl run with pages (and a PDF) whose text is then evaluated.

    texts: url -> [(text, source, visibility, locator), ...]
    """
    data_dir = get_paths().data_dir
    html_path = "pages/test/home.html.gz"
    (data_dir / "pages/test").mkdir(parents=True, exist_ok=True)
    (data_dir / html_path).write_bytes(gzip.compress(HOME_HTML.encode()))
    with session_scope() as session:
        run = Run(
            kind="crawl",
            site_id=1,
            status="completed",
            params={"crawler": crawler},
            started_at=utcnow(),
            finished_at=utcnow(),
            stats={"pages": {"ok": len(texts)}, "files": {}, "segments": {}},
        )
        session.add(run)
        session.flush()
        for url, segments in texts.items():
            kind = "pdf" if url.endswith(".pdf") else "page"
            asset = Asset(
                run_id=run.id,
                site_id=1,
                url=url,
                kind=kind,
                status="ok",
                language="en",
                html_path=html_path if kind == "page" else None,
                screenshot_path="screenshots/x.jpg" if kind == "page" else None,
                file_path="files/r.pdf" if kind == "pdf" else None,
                info={"size": [1366, 2000]},
            )
            session.add(asset)
            session.flush()
            for text, source, visibility, locator in segments:
                session.add(
                    Segment(
                        asset_id=asset.id,
                        text=text,
                        text_source=source,
                        visibility=visibility,
                        locator=locator,
                        extractor="test",
                    )
                )
        run_id = run.id
    findings = evaluate_run(run_id)
    with session_scope() as session:
        session.get(Run, run_id).stats = session.get(Run, run_id).stats | {"findings": findings}
    return run_id


HOME = "https://www.pfizer.com/"
FIRST = {
    HOME: [
        (
            "Welcome to pfizer",
            "heading",
            "visible",
            {"selector": "#hero", "bbox": [10, 20, 300, 40]},
        ),
        ("Old Phizer campaign", "text", "hidden", {"selector": "#promo", "bbox": None}),
        (
            "pfizer medicines",
            "meta:description",
            "metadata",
            {"selector": 'meta[name="description"]'},
        ),
        (
            "Phizer Inc.",
            "json_ld",
            "metadata",
            {"selector": 'script[type="application/ld+json"]:nth-of-type(1)', "path": "name"},
        ),
    ],
    "https://www.pfizer.com/about": [
        ("About Pfizer and Pfzier", "text", "visible", {"selector": "p"})
    ],
    "https://www.pfizer.com/clean": [("Pfizer is fine here", "text", "visible", {"selector": "p"})],
    "https://www.pfizer.com/r.pdf": [
        (
            "Report by pfizer",
            "pdf_text",
            "visible",
            {"page": 2, "bbox": [72, 700, 300, 712], "page_size": [595, 842]},
        ),
    ],
}


@pytest.fixture
def first_run():
    return make_crawl(FIRST)


def test_compliance_scores_and_breakdowns(client, first_run):
    c = client.get(f"/api/runs/{first_run}/compliance").json()
    # home: 4 high violations (40) -> 60; about: near-miss only (not scored) -> 100;
    # clean -> 100; pdf: 1 violation -> 90. Average 87.5.
    assert c["score"] == 87.5
    assert c["assets_checked"] == 4
    assert c["clean_share"] == 50.0  # home and the PDF have high-severity violations
    assert (c["violations"], c["to_review"]) == (5, 1)
    assert c["by_visibility"] == {"visible": 2, "hidden": 1, "metadata": 2}
    assert c["by_asset_kind"] == {"page": 4, "pdf": 1}
    assert c["by_kind"] == {"casing": 3, "disallowed": 2}
    assert c["top_matches"][0] == ["pfizer", 3]
    assert [a["url"] for a in c["worst_assets"]] == [HOME, "https://www.pfizer.com/r.pdf"]
    assert c["worst_assets"][0]["score"] == 60.0
    assert c["changes"] == {"previous_run_id": None, "new": 0, "persisting": 0, "fixed": 0}


def test_findings_list_filters_and_facets(client, first_run):
    page = client.get("/api/findings").json()  # defaults to the latest evaluated crawl
    assert page["run"]["id"] == first_run
    assert page["total"] == 6
    assert page["facets"]["status"] == {"violation": 5, "ambiguous": 1}
    assert page["facets"]["visibility"] == {"visible": 3, "hidden": 1, "metadata": 2}
    hidden = client.get("/api/findings", params={"visibility": "hidden,metadata"}).json()
    assert hidden["total"] == 3
    review = client.get("/api/findings", params={"status": "ambiguous"}).json()["items"]
    assert [(f["matched_text"], f["kind"]) for f in review] == [("Pfzier", "near_miss")]
    search = client.get("/api/findings", params={"q": "report by"}).json()["items"]
    assert [f["asset"]["kind"] for f in search] == ["pdf"]
    paged = client.get("/api/findings", params={"limit": 2, "offset": 4}).json()
    assert len(paged["items"]) == 2 and paged["total"] == 6


def test_changes_since_the_previous_crawl(client, first_run):
    second = dict(FIRST)
    second[HOME] = (
        FIRST[HOME][:1]
        + [  # the hidden promo is gone, a new problem appears
            ("pFizer launch", "text", "visible", {"selector": "p"}),
        ]
        + FIRST[HOME][2:]
    )
    run_id = make_crawl(second, crawler="crawl4ai")
    page = client.get("/api/findings", params={"run_id": run_id}).json()
    assert page["changes"] == {"previous_run_id": first_run, "new": 1, "persisting": 5, "fixed": 1}
    new = client.get("/api/findings", params={"run_id": run_id, "change": "new"}).json()["items"]
    assert [f["matched_text"] for f in new] == ["pFizer"]


def test_csv_export(client, first_run):
    response = client.get("/api/findings.csv", params={"status": "violation"})
    assert response.headers["content-disposition"].endswith(f'run{first_run}.csv"')
    text = response.content.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 5
    pdf_row = next(r for r in rows if r["asset_kind"] == "pdf")
    assert (pdf_row["found"], pdf_row["expected"], pdf_row["pdf_page"]) == ("pfizer", "Pfizer", "2")
    assert response.content.startswith("﻿".encode())  # Excel-friendly UTF-8


def evidence_for(client, text):
    item = next(
        f for f in client.get("/api/findings").json()["items"] if f["segment"]["text"] == text
    )
    return client.get(f"/api/findings/{item['id']}").json()


def test_evidence_for_visible_text_is_the_screenshot_box(client, first_run):
    detail = evidence_for(client, "Welcome to pfizer")
    assert detail["evidence"]["screenshot"] == {
        "path": "screenshots/x.jpg",
        "bbox": [10, 20, 300, 40],
        "page_size": [1366, 2000],
    }
    assert "snippet" not in detail["evidence"]
    assert detail["rule"]["key"] == "BRAND-NAME-001"
    assert detail["previous_id"] is None and detail["next_id"] is not None


def test_evidence_for_hidden_text_and_metadata_is_the_html(client, first_run):
    hidden = evidence_for(client, "Old Phizer campaign")["evidence"]["snippet"]
    assert hidden["html"] == '<div id="promo" style="display:none">Old Phizer campaign</div>'
    meta = evidence_for(client, "pfizer medicines")["evidence"]["snippet"]
    assert meta["html"] == '<meta content="pfizer medicines" name="description"/>'
    json_ld = evidence_for(client, "Phizer Inc.")["evidence"]["snippet"]
    assert '"name": "Phizer Inc."' in json_ld["html"] and json_ld["path"] == "name"


def test_evidence_for_pdf_is_the_page_box(client, first_run):
    detail = evidence_for(client, "Report by pfizer")
    assert detail["evidence"]["pdf"] == {
        "file_path": "files/r.pdf",
        "page": 2,
        "bbox": [72, 700, 300, 712],
        "page_size": [595, 842],
        "property": None,
    }


def test_crawler_comparison(client, first_run):
    second = dict(FIRST)
    del second["https://www.pfizer.com/clean"]
    second["https://www.pfizer.com/extra"] = [("Extra page", "text", "visible", {})]
    make_crawl(second, crawler="crawl4ai")
    result = client.get("/api/sites/1/comparison").json()
    assert set(result["crawlers"]) == {"crawlee", "crawl4ai"}
    assert result["crawlers"]["crawlee"]["score"] == 87.5
    assert result["only_in"] == {
        "crawlee": ["https://www.pfizer.com/clean"],
        "crawl4ai": ["https://www.pfizer.com/extra"],
    }


def test_nothing_evaluated_yet(client):
    assert client.get("/api/findings").json()["run"] is None
    assert client.get("/api/compliance").json() is None
    assert client.get("/api/findings/99").status_code == 404
    assert client.get("/api/sites/99/comparison").status_code == 404


def test_javascript_is_served_as_javascript(client):
    for path in ("/app.js", "/vendor/pdf.min.js"):
        assert client.get(path).headers["content-type"].startswith("text/javascript")
