import json

from brandguard.core.db import session_scope
from brandguard.core.models import Run, RunStatus
from brandguard.jobs import tasks
from brandguard.jobs.worker import mark_interrupted_runs, write_heartbeat


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_ui_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "vendor/vue.global.prod.js" in response.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/vendor/vue.global.prod.js").status_code == 200


def test_system_reports_paths_and_offline_worker(client, brandguard_home):
    info = client.get("/api/system").json()
    assert info["home"] == str(brandguard_home.resolve())
    assert info["worker"] == {"online": False, "last_seen": None, "pid": None}


def test_system_reports_online_worker_after_heartbeat(client):
    write_heartbeat()
    assert client.get("/api/system").json()["worker"]["online"] is True


def test_settings_defaults_and_update(client):
    assert client.get("/api/settings").json() == {
        "performance_profile": "balanced",
        "crawler_contact_email": "",
    }
    updated = client.put("/api/settings", json={"performance_profile": "max"}).json()
    assert updated["performance_profile"] == "max"
    assert client.get("/api/settings").json()["performance_profile"] == "max"


def test_settings_rejects_invalid_values(client):
    assert client.put("/api/settings", json={"performance_profile": "turbo"}).status_code == 422
    assert client.put("/api/settings", json={"crawler_contact_email": "nope"}).status_code == 422
    ok = client.put("/api/settings", json={"crawler_contact_email": "me@example.com"})
    assert ok.json()["crawler_contact_email"] == "me@example.com"


def test_profiles_listed(client):
    assert set(client.get("/api/settings/profiles").json()) == {"light", "balanced", "max"}


def test_selftest_run_completes(client, immediate_queue):
    created = client.post("/api/runs", json={"kind": "selftest"})
    assert created.status_code == 201
    run = created.json()
    assert run["status"] == RunStatus.COMPLETED
    assert run["done"] == run["total"] == len(tasks.SELFTEST_STEPS) * tasks.TICKS_PER_STEP
    assert [r["id"] for r in client.get("/api/runs").json()] == [run["id"]]


def test_unknown_run_kind_rejected(client):
    assert client.post("/api/runs", json={"kind": "crawl-everything"}).status_code == 422


def test_run_stays_queued_without_worker(client):
    run = client.post("/api/runs", json={}).json()
    assert run["status"] == RunStatus.QUEUED


def test_cancel_queued_run_then_task_skips_it(client):
    run = client.post("/api/runs", json={}).json()
    cancelled = client.post(f"/api/runs/{run['id']}/cancel").json()
    assert cancelled["status"] == RunStatus.CANCELLED

    tasks.selftest(run["id"])  # the worker picks it up later
    assert client.get(f"/api/runs/{run['id']}").json()["status"] == RunStatus.CANCELLED


def test_cancel_running_run(client, monkeypatch):
    with session_scope() as session:
        run = Run(kind="selftest", status=RunStatus.RUNNING)
        session.add(run)
        session.flush()
        run_id = run.id

    # Request the cancel from inside the second step, as a user clicking Cancel mid-run.
    monkeypatch.setitem(tasks._CHECKS, "storage", lambda: client.post(f"/api/runs/{run_id}/cancel"))
    tasks.selftest(run_id)

    run = client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == RunStatus.CANCELLED
    assert run["done"] < run["total"]


def test_cancel_finished_run_conflicts(client, immediate_queue):
    run = client.post("/api/runs", json={}).json()
    assert client.post(f"/api/runs/{run['id']}/cancel").status_code == 409


def test_failed_check_marks_run_failed(client, immediate_queue, monkeypatch):
    def broken():
        raise OSError("disk is full")

    monkeypatch.setitem(tasks._CHECKS, "storage", broken)
    run = client.post("/api/runs", json={}).json()
    assert run["status"] == RunStatus.FAILED
    assert run["error"] == "disk is full"


def test_missing_run_is_404(client):
    assert client.get("/api/runs/999").status_code == 404
    assert client.post("/api/runs/999/cancel").status_code == 404
    assert client.get("/api/runs/999/events").status_code == 404


def test_events_stream_ends_with_finished_run(client, immediate_queue):
    run = client.post("/api/runs", json={}).json()
    with client.stream("GET", f"/api/runs/{run['id']}/events") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    data_lines = [line for line in body.splitlines() if line.startswith("data: ")]
    assert len(data_lines) == 1
    assert json.loads(data_lines[0][len("data: ") :])["status"] == RunStatus.COMPLETED


def test_worker_start_marks_running_runs_interrupted(client):
    with session_scope() as session:
        session.add(Run(kind="selftest", status=RunStatus.RUNNING))
    assert mark_interrupted_runs() == 1
    assert client.get("/api/runs").json()[0]["status"] == RunStatus.INTERRUPTED
