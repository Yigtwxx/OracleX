"""
No job poll route may answer for a job belonging to another feature.

Every kind of background job — reports, news notes, Polymarket verdicts and
origin traces, BIST radar scans, chat turns — lives in one process-wide
registry in `services/analysis_jobs.py`, and `Job.to_dict()` serialises
`result` and `partial_result`. A poll route that looks a job up by id alone is
therefore a reader for every other feature's jobs, and four of them did exactly
that: `/api/analysis/jobs/{id}`, `/api/news/analysis/jobs/{id}` and both
Polymarket poll routes checked neither kind nor owner. A chat turn's id is
effectively a bearer token for someone's question and the model's answer, and
any of those four handed both back.

The tests are written against the *route table* rather than against a list of
paths, so a poll route added to a new feature tomorrow is covered the day it is
written. That is deliberate: this bug was not a missing check so much as a
convention — documented on `Job.owner_id`, applied correctly in
`routers/chat.py` — that four other authors never had reason to read.
"""

from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import analysis, bist, chat, news, polymarket
from services import analysis_jobs

# Every router that exposes a job poll route. A new one belongs here; if it is
# forgotten, `test_every_job_route_is_covered` is what notices.
ROUTER_MODULES = (analysis, bist, chat, news, polymarket)

# Planted in the finished job's result. If this string reaches a response body
# through any route but chat's, the isolation this file exists for is gone.
SECRET = "the-question-only-its-owner-may-read"

OWNER = "owner-account-id"


@pytest.fixture(autouse=True)
def _clean_jobs() -> Iterator[None]:
    analysis_jobs._jobs.clear()
    yield
    analysis_jobs._jobs.clear()


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    for module in ROUTER_MODULES:
        app.include_router(module.router)
    # `raise_server_exceptions=False` so a route that fails for an unrelated
    # reason is reported as a 500 and fails its assertion, rather than aborting
    # the whole parametrised run with a traceback from one endpoint.
    return TestClient(app, raise_server_exceptions=False)


def job_routes(methods: set[str]) -> list[tuple[str, str]]:
    """Every `{job_id}` route across the routers, as (method, path) pairs."""
    found = []
    for module in ROUTER_MODULES:
        for route in module.router.routes:
            path = getattr(route, "path", "")
            if "{job_id}" not in path:
                continue
            for method in sorted(getattr(route, "methods", set()) & methods):
                found.append((method, path))
    return found


GET_ROUTES = job_routes({"GET"})
ALL_ROUTES = job_routes({"GET", "DELETE"})


async def _finished_chat_job() -> analysis_jobs.Job:
    """A settled chat turn owned by OWNER, with the secret in its result."""

    async def runner(_controls):
        return {"response": SECRET}

    job = await analysis_jobs.start(
        "isolation-probe", analysis_jobs.KIND_CHAT, [], runner, owner_id=OWNER
    )
    if job.task:
        await job.task
    return job


def test_every_job_route_is_covered():
    """
    The discovery above must actually be finding routes.

    Without this, a rename that made `job_routes` return nothing would turn
    every parametrised test below into a silent pass — the failure mode of a
    generated test suite, and worse than no test at all.
    """
    assert len(GET_ROUTES) >= 5
    assert ("GET", "/api/chat/jobs/{job_id}") in GET_ROUTES


@pytest.mark.parametrize("method,path", ALL_ROUTES)
async def test_no_route_leaks_another_kinds_job(client, method, path):
    """
    The regression, stated over the whole route table at once.

    An anonymous caller holding a chat job's id must get nothing from any of
    these — 404 from the routes scoped to another kind, and 404 from chat's own
    route too, since the turn belongs to someone else.
    """
    job = await _finished_chat_job()

    response = client.request(method, path.replace("{job_id}", job.id))

    assert response.status_code == 404, f"{method} {path} answered {response.status_code}"
    assert SECRET not in response.text


@pytest.mark.parametrize("method,path", ALL_ROUTES)
async def test_no_route_leaks_a_report_job_either(client, method, path):
    """
    Not a chat-only rule.

    Reports are public, so nothing here is a disclosure — but a Polymarket poll
    answering with a report is a bug in its own right, and asserting the
    property for a second kind is what distinguishes "each route is scoped to
    its kind" from "chat happens to be special-cased".
    """

    async def runner(_controls):
        return {"summary": SECRET}

    job = await analysis_jobs.start("daily", analysis_jobs.KIND_REPORT, [], runner)
    if job.task:
        await job.task

    response = client.request(method, path.replace("{job_id}", job.id))

    if path.startswith("/api/analysis/jobs"):
        # Its own route, and reports carry no owner — this one must answer.
        assert response.status_code == 200
        assert SECRET in response.text
    else:
        assert response.status_code == 404, f"{method} {path} answered {response.status_code}"
        assert SECRET not in response.text


@pytest.mark.parametrize("method,path", ALL_ROUTES)
async def test_unknown_job_id_is_a_404_everywhere(client, method, path):
    """A missing job and a forbidden one must be indistinguishable to a caller."""
    response = client.request(method, path.replace("{job_id}", "no-such-job"))

    assert response.status_code == 404


# ── the helper the routes now share ──────────────────────────────────────────


async def test_readable_job_refuses_a_mismatched_kind():
    job = await _finished_chat_job()

    assert await analysis_jobs.readable_job(job.id, analysis_jobs.KIND_REPORT) is None


async def test_readable_job_refuses_a_different_owner():
    job = await _finished_chat_job()

    found = await analysis_jobs.readable_job(
        job.id, analysis_jobs.KIND_CHAT, viewer_id="somebody-else"
    )

    assert found is None


async def test_readable_job_returns_an_owned_job_to_its_owner():
    job = await _finished_chat_job()

    found = await analysis_jobs.readable_job(job.id, analysis_jobs.KIND_CHAT, viewer_id=OWNER)

    assert found is not None and found.id == job.id


async def test_readable_job_ignores_viewer_for_a_public_kind():
    """
    A report is the same document for everyone, so passing a viewer must not
    narrow it. This is what lets a route hand its caller's id in unconditionally
    — the kind decides whether it matters, not the call site.
    """

    async def runner(_controls):
        return {"summary": "public"}

    job = await analysis_jobs.start("weekly", analysis_jobs.KIND_REPORT, [], runner)
    if job.task:
        await job.task

    found = await analysis_jobs.readable_job(
        job.id, analysis_jobs.KIND_REPORT, viewer_id="a-stranger"
    )

    assert found is not None
