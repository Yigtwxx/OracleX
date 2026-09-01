"""
Tests for what the application startup sequence is allowed to block on.

Uvicorn binds its listening socket only *after* the lifespan startup completes
(`Server.startup()` awaits `lifespan.startup()` before creating the servers), so
every second spent before `yield` is a second the port refuses connections —
including connections to `/api/system/readiness`, the one endpoint whose job is
to tell the frontend how startup is going.

That makes "startup does no slow work before yielding" a correctness property,
not a performance preference: break it and the boot splash has nothing to show
but a spinner, and long enough breaks it entirely as the frontend's
unreachable budget expires and the user is told the server is down.
"""

import asyncio
import time

import pytest


# Slow enough that a blocking startup cannot possibly come in under the budget,
# short enough to keep the suite quick.
SLOW_STEP_SECONDS = 1.5

# What "does not block" means in wall-clock terms. Generous versus
# 2 x SLOW_STEP_SECONDS so a loaded CI box cannot make this flap.
STARTUP_BUDGET_SECONDS = 0.5


@pytest.fixture
def stubbed_startup(monkeypatch):
    """
    Neutralise everything the lifespan touches, then make the two network-bound
    warm-ups deliberately slow.

    The assertions are about *ordering*, not about the warm-ups themselves, so
    the real work is replaced wholesale — nothing here reaches the network.
    """
    from config import settings
    from services import asset_registry, llm, rag_embeddings, rag_rerank, scheduler_service
    from services.bist import kap_service
    from services.liquidation_service import liquidation_service

    # `settings` is a pydantic model, which refuses attribute assignment for
    # anything that is not a declared field — so the method is patched on the
    # class and the plain field on the instance.
    monkeypatch.setattr(type(settings), "validate_required", lambda self: None)
    monkeypatch.setattr(settings, "USE_AI", True)

    async def slow_warm_up() -> None:
        await asyncio.sleep(SLOW_STEP_SECONDS)

    async def slow_health() -> bool:
        await asyncio.sleep(SLOW_STEP_SECONDS)
        return True

    class FakeProvider:
        name = "fake-cloud"
        model = "fake-model"

    monkeypatch.setattr(asset_registry, "warm_up", slow_warm_up)
    monkeypatch.setattr(llm, "llm_health", slow_health)
    monkeypatch.setattr(llm, "get_chain", lambda: [FakeProvider()])

    async def noop_start() -> None:
        return None

    monkeypatch.setattr(liquidation_service, "start", noop_start)
    monkeypatch.setattr(liquidation_service, "stop", noop_start)
    monkeypatch.setattr(scheduler_service, "start_scheduler", lambda: None)
    monkeypatch.setattr(scheduler_service, "stop_scheduler", lambda: None)

    async def noop_news() -> None:
        return None

    monkeypatch.setattr(scheduler_service, "update_news_cache_job", noop_news)

    # Blocking on purpose. Loading an embedding model — and, for the reranker, a
    # cross-encoder — is synchronous CPU work, so the stubs are synchronous too:
    # anything that runs them on the event loop rather than in a thread shows up
    # here as a stalled loop.
    def blocking_warm_up():
        time.sleep(SLOW_STEP_SECONDS)

    monkeypatch.setattr(rag_embeddings, "warm_up", blocking_warm_up)
    monkeypatch.setattr(rag_rerank, "warm_up", blocking_warm_up)

    # The KAP warm-up is the one that reaches the network even when it succeeds:
    # it answers from the tape on disk and then schedules a background walk to
    # catch up, which is real paced HTTP landing in whichever loop these tests
    # are timing. Stubbed to nothing so the ordering assertions measure the
    # lifespan rather than KAP's rate limiter.
    async def no_tape(*args, **kwargs) -> list:
        return []

    monkeypatch.setattr(kap_service, "fetch_tape", no_tape)


async def test_startup_yields_before_the_slow_warm_ups_finish(stubbed_startup):
    """
    The port must open while the warm-ups are still running.

    This is the bug that made a cold start show "Sunucuya bağlanılamıyor": the
    registry fetch and the LLM health check ran to completion before `yield`, so
    nothing was listening for the first ~15 seconds of every boot.
    """
    import main

    started_at = time.monotonic()
    async with main.lifespan(main.create_app()):
        elapsed = time.monotonic() - started_at

    assert elapsed < STARTUP_BUDGET_SECONDS, (
        f"Startup blocked for {elapsed:.1f}s before serving; the readiness "
        f"endpoint is unreachable for that whole window"
    )


async def test_readiness_reports_every_step_as_soon_as_startup_yields(stubbed_startup):
    """
    The splash must be able to name what it is waiting for on its first poll.

    Registering the steps before running any of them is what turns the splash
    from an unexplained spinner into a list of labelled work.
    """
    import main
    from services.readiness import readiness

    async with main.lifespan(main.create_app()):
        snapshot = readiness.snapshot()

    assert [step["key"] for step in snapshot["steps"]] == [
        "registry",
        "liquidations",
        "news",
        "heatmap",
        "macro",
        "ownership",
        "kap",
        "llm",
        "rag",
    ], "Every step must be listed before any of them has finished"
    assert snapshot["ready"] is False, "Warm-ups are still running, so the gate stays shut"


async def test_a_slow_warm_up_still_holds_the_gate_shut(stubbed_startup):
    """
    Yielding early must not be mistaken for being ready.

    Serving the readiness endpoint sooner is the point; opening the UI onto a
    cold registry is not.
    """
    import main
    from services.readiness import readiness

    async with main.lifespan(main.create_app()):
        registry_step = next(s for s in readiness.snapshot()["steps"] if s["key"] == "registry")
        assert registry_step["state"] in ("pending", "running"), (
            "A registry warm-up that has not finished must not read as settled"
        )
        assert readiness.ready is False


async def test_warm_ups_do_not_stall_the_event_loop(stubbed_startup):
    """
    An open port is worth nothing if the loop behind it cannot answer.

    Loading the embedding models is synchronous work; run it on the loop and
    every request queues behind it, so the readiness poll goes unanswered for
    seconds even though uvicorn is listening. The loop must keep turning.
    """
    import main

    async with main.lifespan(main.create_app()):
        # Sample how long the loop takes to come back to us, the way a queued
        # request would experience it.
        worst_gap = 0.0
        for _ in range(20):
            before = time.monotonic()
            await asyncio.sleep(0.01)
            worst_gap = max(worst_gap, time.monotonic() - before - 0.01)

    assert worst_gap < 0.2, (
        f"Event loop stalled for {worst_gap:.2f}s during startup; a request "
        f"arriving then would have waited that long for a reply"
    )
