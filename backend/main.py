"""
Oracle-X Backend API
FastAPI server providing news feeds, AI analysis, and blockchain verification.

All endpoint logic lives in router modules under the `routers/` directory.
This file wires configuration, logging, middleware, lifecycle events, and
router registration together via the `create_app()` application factory.
"""

# Suppress noisy third-party warnings before other imports.
import warnings

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")
warnings.filterwarnings("ignore", category=DeprecationWarning)

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from config import settings
from services.liquidation_service import liquidation_service

# Import all routers
from routers import (
    admin,
    auth,
    news,
    llm as llm_router,
    market,
    liquidation,
    watchlist,
    home,
    macro,
    live,
    chains,
    analysis,
    rag,
    chat,
    profile,
    exchanges,
    websocket,
    community,
    social,
    ownership,
    polymarket,
    system,
)

logger = logging.getLogger("oracle_x")


def _configure_logging() -> None:
    """Configure root logging once at startup (level driven by settings)."""
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# LIFECYCLE
# ═══════════════════════════════════════════════════════════════════════════════

# Strong references to the startup warm-up tasks. The event loop only holds a
# weak one, so without this a task can be collected mid-flight — and a collected
# registry warm-up would leave the boot gate waiting on a step that never
# reports back, until its deadline finally forces the UI open.
_startup_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> asyncio.Task:
    """Run `coro` in the background, keeping it alive until it finishes."""
    task = asyncio.create_task(coro)
    _startup_tasks.add(task)
    task.add_done_callback(_startup_tasks.discard)
    return task


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown of background services."""
    # --- Startup ---
    # Fail fast on missing credentials rather than 500-ing on first request.
    settings.validate_required()

    # Not a fatal condition — the app serves fine with nobody administering it —
    # but a typo in ADMIN_EMAILS locks the panel away silently, so say it out
    # loud either way.
    if settings.admin_emails:
        logger.info("Admin panel enabled for %d address(es)", len(settings.admin_emails))
    else:
        logger.warning("ADMIN_EMAILS is empty — the admin panel is closed to everyone")

    # The scrape ladder's browser rung is on by default, and it needs binaries
    # that pip does not install (`./venv/bin/scrapling install`). Missing them
    # is not fatal — the ladder reports "that site needs a browser and one is
    # not available" and the turn answers without it — but a deployment that
    # thinks it can read Reddit and silently cannot is worth one loud line.
    if settings.SCRAPLING_ALLOW_BROWSER:
        try:
            from scrapling.fetchers import AsyncStealthySession  # noqa: F401
        except Exception as e:  # noqa: BLE001 — a missing browser is a warning
            logger.warning(
                "SCRAPLING_ALLOW_BROWSER is on but no browser is available (%s). "
                "JavaScript-only sites will be reported as unreadable. "
                "Run `./venv/bin/scrapling install` to enable them.",
                e,
            )

    # Declare the warm-up steps before running any of them, so the frontend's
    # boot gate can show the whole list from its very first poll.
    from services.readiness import readiness, register_startup_steps

    register_startup_steps()

    # Nothing from here to `yield` may block on network work. Uvicorn binds its
    # listening socket only after this function yields, so every second spent
    # here is a second the boot gate's own poll of /api/system/readiness is
    # refused — leaving the splash with nothing to name and, once the gate's
    # unreachable budget expires, telling the user the server is down. The
    # warm-ups therefore run as tasks and report progress through `readiness`.

    # Prime the asset registry (coin/stock universes, top pairs) before anything
    # asks for it, so the first request isn't on the cold path. Still required:
    # the gate waits for this task, it just no longer waits behind a shut port.
    from services import asset_registry

    async def _warm_registry():
        readiness.start("registry")
        try:
            await asset_registry.warm_up()
            readiness.succeed("registry")
        except Exception as e:
            # warm_up already degrades to disk cache and seeds internally, so this
            # only fires on something structural. Recorded rather than raised: the
            # boot gate reports it far better than a failed process start would.
            readiness.fail("registry", e)
            logger.error("Asset registry warm-up failed: %s", e)

    registry_task = _spawn(_warm_registry())

    readiness.start("liquidations")
    try:
        await liquidation_service.start()
        readiness.succeed("liquidations")
    except Exception as e:
        readiness.fail("liquidations", e)
        logger.error("Liquidation service failed to start: %s", e)

    # Start background scheduler for news fetching + RAG indexing.
    from services.scheduler_service import start_scheduler, update_news_cache_job

    start_scheduler()

    # Pull the local model into memory before the news burst needs it. Loading a
    # large model costs tens of seconds, and every call that races that load
    # times out — which is what filled the log with failed symbol detections on
    # every restart. Runs first so it has a head start on the news fetch, but in
    # the background: a slow warm-up must not hold up serving.
    async def _warm_local_llm():
        readiness.start("llm")
        if not settings.USE_AI:
            readiness.succeed("llm")  # nothing to load; not a failure
            return
        try:
            from services import llm

            chain = llm.get_chain()
            if not chain or chain[0].name != "ollama":
                readiness.succeed("llm")  # a cloud provider has no load to pay for
                return
            await chain[0].generate(llm.GenerationRequest(prompt="ok", max_tokens=1, timeout=600.0))
            logger.info("Local LLM (%s) warmed up", chain[0].model)
            readiness.succeed("llm")
        except Exception as e:
            # Non-fatal: the model loads on first real use instead, and the
            # provider chain covers the calls that time out meanwhile.
            logger.warning("Local LLM warm-up failed: %s", e)
            readiness.fail("llm", e)

    _spawn(_warm_local_llm())

    # Trigger an immediate news fetch in background so the cache isn't empty.
    async def _initial_news_fetch():
        # Headline attribution resolves every symbol against the registry's
        # listings, so wait for the registry rather than racing it into a
        # duplicate fetch of the same universes.
        await registry_task
        readiness.start("news")
        try:
            await update_news_cache_job()
            readiness.succeed("news")
        except Exception as e:
            # The job swallows its own errors, so reaching here means something
            # outside it broke. Optional either way — the app opens without news.
            logger.warning("Initial news fetch failed: %s", e)
            readiness.fail("news", e)

    _spawn(_initial_news_fetch())

    # Build the heatmap board once at boot so the first visitor is not the one
    # paying for the paced per-coin detail rotation. Optional and backgrounded:
    # the board is one page of the app, and a CoinGecko outage must not hold the
    # splash open for everything else.
    async def _warm_heatmap():
        # Needs the crypto universe to know which coins the board covers.
        await registry_task
        readiness.start("heatmap")
        try:
            from services.heatmap_service import refresh_heatmap

            if await refresh_heatmap() is None:
                raise RuntimeError("heatmap board could not be built")
            readiness.succeed("heatmap")
        except Exception as e:
            logger.warning("Heatmap warm-up failed: %s", e)
            readiness.fail("heatmap", e)

    _spawn(_warm_heatmap())

    # Build the macro board once at boot. It is ~26 upstream requests behind a
    # single cache entry, so leaving it cold means the first visitor to /macro —
    # or anyone loading the global ticker — pays for all of them at once.
    async def _warm_macro_board():
        readiness.start("macro")
        try:
            from services.macro_board_service import fetch_macro_board

            await fetch_macro_board()
            readiness.succeed("macro")
        except Exception as e:
            logger.warning("Macro board warm-up failed: %s", e)
            readiness.fail("macro", e)

    _spawn(_warm_macro_board())

    # Build the ownership board if the stored one has aged out. The daily cron
    # is the normal path; this only covers the cases it cannot — a fresh install
    # before the first noon, or a machine that was off when noon passed. It is
    # deliberately not an unconditional rebuild: the sources behind this board
    # rate-limit hard, and a restart loop would exhaust the day's budget.
    async def _warm_ownership():
        readiness.start("ownership")
        try:
            from services.ownership.refresh import ensure_board

            await ensure_board()
            readiness.succeed("ownership")
        except Exception as e:
            logger.warning("Ownership warm-up failed: %s", e)
            readiness.fail("ownership", e)

    _spawn(_warm_ownership())

    # Warm the RAG embedding model in a background thread so the first AI
    # request never blocks the event loop downloading/loading it. Non-fatal:
    # if it fails (e.g. offline), RAG simply degrades to empty context.
    async def _warm_embedding_models():
        readiness.start("rag")
        try:

            def _load():
                # Imported in the worker thread, not just called there: pulling
                # in sentence-transformers is itself seconds of synchronous
                # work, and on the event loop it stalls every request —
                # including the boot gate's own readiness poll, which is what
                # kept the port silent for five seconds after it had opened.
                #
                # Off the event loop is not the same as cheap: the cross-encoder
                # picks an accelerator when there is one and caps its core count
                # when there is not (see services/rag_device), because an uncapped
                # load saturated the machine and starved the frontend dev server
                # into ChunkLoadError.
                #
                # One warm-up covers both stores now that they share a backend;
                # they used to hold two copies of the same model in memory.
                from services import rag_embeddings, rag_rerank

                rag_embeddings.warm_up()
                rag_rerank.warm_up()

            await asyncio.to_thread(_load)
            logger.info("RAG embedding model warmed up")
            readiness.succeed("rag")
        except Exception as e:
            logger.warning("RAG embedding warm-up failed (RAG will degrade): %s", e)
            readiness.fail("rag", e)

    _spawn(_warm_embedding_models())

    # Report the resolved LLM provider chain, and warn loudly (but non-fatally)
    # if nothing in it is usable — otherwise every AI feature silently degrades.
    # In the background: the health check reaches a provider, and against a local
    # Ollama that means waiting for the model to load — roughly ten seconds of
    # every cold start, previously spent with the port still shut.
    async def _report_llm_chain():
        if not settings.USE_AI:
            return
        from services import llm

        chain = llm.get_chain()
        if not chain:
            logger.warning(
                "No usable LLM provider. Set LLM_PROVIDER (one of: %s) and the "
                "matching API key in .env. AI features will use fallbacks.",
                ", ".join(llm.preset_names()),
            )
            return
        logger.info("LLM chain: %s", " → ".join(f"{p.name}:{p.model}" for p in chain))
        if not await llm.llm_health():
            primary = chain[0]
            hint = (
                f"Is `ollama serve` running, and have you pulled {primary.model}?"
                if primary.name == "ollama"
                else "Check the API key and model id."
            )
            logger.warning("No LLM provider in the chain responded to a health check. %s", hint)

    _spawn(_report_llm_chain())

    yield

    # --- Shutdown ---
    await liquidation_service.stop()

    from services.scheduler_service import stop_scheduler

    stop_scheduler()

    # Stop price streaming if it was started.
    try:
        from services.websocket_service import price_streaming_service

        await price_streaming_service.stop()
    except Exception:
        logger.debug("Price streaming service was not running at shutdown.")


# ═══════════════════════════════════════════════════════════════════════════════
# APP FACTORY
# ═══════════════════════════════════════════════════════════════════════════════


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    _configure_logging()

    app = FastAPI(
        title="Oracle-X API",
        description="Financial Intelligence Terminal Backend",
        version="1.3.0",
        lifespan=lifespan,
    )

    # CORS middleware for the Next.js frontend.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Several endpoints return large, highly repetitive JSON grids (the
    # liquidation map is a few hundred KB uncompressed) and compress ~10x.
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        """Log unhandled errors with a traceback and return a structured 500."""
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    @app.get("/")
    async def root():
        """Health check endpoint.

        The version is read off the app rather than repeated here — the literal
        that used to sit in this dict was left at 1.0.0 through two releases,
        which made the one endpoint a caller hits first the least trustworthy
        thing to ask about the version.
        """
        return {
            "status": "online",
            "service": app.title,
            "version": app.version,
            "timestamp": datetime.now().isoformat(),
        }

    # Register routers.
    app.include_router(
        news.router
    )  # /api/news, /api/analyze, /api/symbols, /api/technical, /api/rag/stats
    app.include_router(llm_router.router)  # /api/llm/status
    app.include_router(
        market.router
    )  # /api/fear-greed, /api/market-overview, /api/nasdaq-overview, /api/market/indices, /api/heatmap
    app.include_router(liquidation.router)  # /api/liquidations/*, /api/market/candles
    app.include_router(watchlist.router)  # /api/home/watchlist
    app.include_router(home.router)  # /api/home/*, /api/onchain/whales
    app.include_router(macro.router)  # /api/macro/board
    app.include_router(live.router)  # /api/live/events, /api/live/streams, /api/live/tape
    app.include_router(chains.router)  # /api/chains/board
    app.include_router(polymarket.router)  # /api/polymarket/board, /api/polymarket/markets/*
    app.include_router(
        analysis.router
    )  # /api/analysis/reports, /api/analysis/jobs, /api/analysis/notes
    app.include_router(rag.router)  # /api/rag/initialize, /api/rag/stats (v2), /api/rag/query
    app.include_router(chat.router)  # /api/chat, /api/chat/status, /api/chat/history
    app.include_router(auth.router)  # /api/auth/email/precheck
    app.include_router(profile.router)  # /api/profile/*
    app.include_router(exchanges.router)  # /api/exchanges, /api/multi-exchange, /api/arbitrage
    app.include_router(websocket.router)  # /ws/prices, /api/websocket/status
    app.include_router(community.router)  # /api/community/*
    app.include_router(social.router)  # /api/social/* — DMs, blocks, own activity
    app.include_router(ownership.router)  # /api/ownership/board, /api/ownership/entities/*
    app.include_router(ownership.admin_router)  # /api/admin/ownership/refresh
    # Two objects: `/api/admin/me` answers any signed-in caller, everything else
    # is behind a router-level require_admin.
    app.include_router(admin.session_router)  # /api/admin/me
    app.include_router(admin.router)  # /api/admin/*
    app.include_router(system.router)  # /api/system/readiness, /api/system/health

    return app


# Module-level app instance for `uvicorn main:app`.
app = create_app()


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRYPOINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
