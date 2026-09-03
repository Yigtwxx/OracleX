"""
The Radar's three routes.

What is pinned: a scan is a job the client polls, not a request that blocks
for a minute; a second click joins the running scan; a horizon the profiles do
not know is a 422; and a horizon that has never been scanned is a 404, so the
page shows the button rather than a result that reads as "nothing passed".
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from main import app
from services import analysis_jobs
from services.bist.radar import scan as radar_scan


@pytest.fixture(autouse=True)
def _clean_jobs():
    analysis_jobs._jobs.clear()
    analysis_jobs._lock = None
    yield
    analysis_jobs._jobs.clear()
    analysis_jobs._lock = None


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def slow_scan(monkeypatch):
    """A scan that runs until released, so an in-flight job can be observed."""
    release = asyncio.Event()
    calls = {"count": 0}

    async def fake_run(profile, controls):
        calls["count"] += 1
        controls.on_stage("technical")
        controls.on_partial({"progress": {"stage": "technical", "done": 3, "total": 40}})
        await release.wait()
        return {"horizon": profile.key, "candidates": [], "universe": []}

    monkeypatch.setattr(radar_scan, "run_scan", fake_run)
    return release, calls


def test_unknown_horizon_is_rejected(client):
    assert client.post("/api/bist/radar/scan?horizon=daily").status_code == 422
    assert client.get("/api/bist/radar?horizon=daily").status_code == 422


def test_no_scan_yet_is_a_404_not_an_empty_board(client, monkeypatch):
    monkeypatch.setattr(radar_scan, "read_last", lambda horizon: None)
    response = client.get("/api/bist/radar?horizon=swing")
    assert response.status_code == 404


def test_last_result_is_served_from_the_store(client, monkeypatch):
    monkeypatch.setattr(
        radar_scan, "read_last", lambda horizon: {"horizon": horizon, "candidates": []}
    )
    payload = client.get("/api/bist/radar?horizon=position").json()
    assert payload["horizon"] == "position"


def test_a_scan_is_a_job_and_a_second_click_joins_it(client, slow_scan):
    release, calls = slow_scan
    with client:
        first = client.post("/api/bist/radar/scan?horizon=swing")
        assert first.status_code == 202
        job_id = first.json()["job_id"]
        assert first.json()["stages"][0]["key"] == "universe"

        second = client.post("/api/bist/radar/scan?horizon=swing")
        assert second.json()["job_id"] == job_id
        assert calls["count"] == 1, "the second click must not start a second walk"

        polled = client.get(f"/api/bist/radar/jobs/{job_id}").json()
        assert polled["status"] == "running"
        assert polled["partial_result"]["progress"]["done"] == 3

        release.set()
        for _ in range(50):
            polled = client.get(f"/api/bist/radar/jobs/{job_id}").json()
            if polled["status"] == "done":
                break
        assert polled["status"] == "done"
        assert polled["result"]["horizon"] == "swing"


def test_a_different_horizon_is_a_different_job(client, slow_scan):
    release, calls = slow_scan
    with client:
        a = client.post("/api/bist/radar/scan?horizon=swing").json()["job_id"]
        b = client.post("/api/bist/radar/scan?horizon=short").json()["job_id"]
        assert a != b
        release.set()


def test_unknown_job_is_a_404(client):
    assert client.get("/api/bist/radar/jobs/nope").status_code == 404


def test_a_running_scan_can_be_cancelled(client, slow_scan):
    release, _calls = slow_scan
    with client:
        job_id = client.post("/api/bist/radar/scan?horizon=swing").json()["job_id"]
        cancelled = client.delete(f"/api/bist/radar/jobs/{job_id}").json()
        assert cancelled["status"] == "error"
        assert "cancel" in (cancelled["error"] or "").lower()
        # The next click starts a fresh scan rather than joining the dead one.
        again = client.post("/api/bist/radar/scan?horizon=swing").json()
        assert again["job_id"] != job_id
        release.set()


def test_cancelling_an_unknown_job_is_a_404(client):
    assert client.delete("/api/bist/radar/jobs/nope").status_code == 404
