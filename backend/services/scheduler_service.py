"""
Background Scheduler Service
Manages automated tasks like news fetching and data aggregation.
"""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

from config import settings

# Correct import path
from services.news_service import fetch_all_news
from utils import log_header, log_step, log_success, log_error, update_news_cache

# Global scheduler instance
scheduler = AsyncIOScheduler()


async def update_news_cache_job():
    """
    Background job to fetch news and update the global cache.
    """
    try:
        # Gray color for log_step message part isn't standard in utils, using standard log_step
        log_step("🔄", "Background Job: Fetching fresh news...")

        # Fetch news from all sources
        items = await fetch_all_news()

        if items:
            # Update the cache
            update_news_cache(items)
            log_success(f"Background Job: Cache updated with {len(items)} news items")
        else:
            log_error("Background Job: No news items fetched")

    except Exception as e:
        log_error(f"Background Job Error: {e}")


def start_scheduler():
    """Start the background scheduler."""
    if not scheduler.running:
        # Add news update job - runs every 10 minutes
        # Also run immediately on startup is handled in main.py startup event
        scheduler.add_job(
            update_news_cache_job,
            trigger=IntervalTrigger(minutes=settings.NEWS_FETCH_INTERVAL_MINUTES),
            id="news_update_job",
            name="Update News Cache",
            replace_existing=True,
        )

        # Add RAG auto-indexing job - index news into vector DB every 30 minutes
        async def rag_auto_index_job():
            try:
                from services.rag_v2_service import auto_index_recent_news

                await auto_index_recent_news()
            except Exception as e:
                log_error(f"RAG auto-index error: {e}")

        scheduler.add_job(
            rag_auto_index_job,
            trigger=IntervalTrigger(minutes=settings.RAG_INDEX_INTERVAL_MINUTES),
            id="rag_auto_index_job",
            name="RAG Auto-Index News",
            replace_existing=True,
        )

        # Rebuild the heatmap board out of band. The board's per-coin detail
        # rotation is paced against CoinGecko's rate limit and takes tens of
        # seconds, which is far too long to sit inside a request — the regime
        # snapshot's five second feed timeout used to cancel it mid-sleep,
        # spending the rate-limit budget and discarding the results.
        async def heatmap_refresh_job():
            try:
                from services.heatmap_service import refresh_heatmap

                await refresh_heatmap()
            except Exception as e:
                log_error(f"Heatmap refresh error: {e}")

        scheduler.add_job(
            heatmap_refresh_job,
            trigger=IntervalTrigger(minutes=settings.HEATMAP_REFRESH_INTERVAL_MINUTES),
            id="heatmap_refresh_job",
            name="Refresh Heatmap Board",
            replace_existing=True,
            # A refresh can outlast its own interval. Stacking them would
            # multiply the request rate against the limit they are paced for.
            max_instances=1,
            coalesce=True,
        )

        # Live tab. Both jobs exist to keep expensive work off the request path
        # rather than to make the data fresher than its TTL: the broadcast probe
        # downloads a megabyte per channel, and paying that inside a page load —
        # once per open tab, per poll — is what the schedule avoids.
        #
        # A zero interval disables the probe. The tab degrades to YouTube's own
        # channel embed, which resolves the current stream at play time without
        # anyone having to detect it.
        if settings.LIVE_STREAM_PROBE_INTERVAL_MINUTES > 0:

            async def live_streams_probe_job():
                try:
                    from services.live_stream_service import probe_all

                    await probe_all(force=True)
                except Exception as e:
                    log_error(f"Live stream probe error: {e}")

            scheduler.add_job(
                live_streams_probe_job,
                trigger=IntervalTrigger(minutes=settings.LIVE_STREAM_PROBE_INTERVAL_MINUTES),
                id="live_streams_probe_job",
                name="Probe Live Broadcast Channels",
                replace_existing=True,
                # Seven page fetches can outrun a three minute interval on a
                # slow link, and stacking them would multiply the bandwidth.
                max_instances=1,
                coalesce=True,
            )

        async def live_events_refresh_job():
            try:
                from services.live_events_service import fetch_live_events

                await fetch_live_events()
            except Exception as e:
                log_error(f"Live events refresh error: {e}")

        scheduler.add_job(
            live_events_refresh_job,
            trigger=IntervalTrigger(minutes=settings.LIVE_EVENTS_REFRESH_INTERVAL_MINUTES),
            id="live_events_refresh_job",
            name="Refresh Live Event Calendar",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # Ownership board. Once a day rather than on an interval: every source
        # behind it publishes quarterly, monthly or on-event, so polling would
        # re-download the same filing ninety times and learn nothing — while
        # spending an SEC and CoinGecko rate limit shared with nothing else.
        #
        # The first CronTrigger in this file. Its timezone is explicit and lives
        # in settings because noon is a claim about a place, and the container
        # clock is UTC.
        async def ownership_refresh_job():
            try:
                from services.ownership.refresh import refresh_ownership

                report = await refresh_ownership()
                log_success(
                    "Ownership refresh: "
                    f"{report.entities_ok}/{report.entities_total} entities, "
                    f"{report.moves_new} new moves, "
                    f"{report.sources_failed} source(s) unavailable"
                )
            except Exception as e:
                log_error(f"Ownership refresh error: {e}")

        scheduler.add_job(
            ownership_refresh_job,
            trigger=CronTrigger(
                hour=settings.OWNERSHIP_REFRESH_HOUR,
                minute=0,
                timezone=settings.OWNERSHIP_REFRESH_TIMEZONE,
            ),
            id="ownership_refresh_job",
            name="Refresh Ownership Board",
            replace_existing=True,
            # A run can outlast an hour when SEC is being paced; a second
            # concurrent run would double the request rate the first is staying
            # deliberately under.
            max_instances=1,
            coalesce=True,
            # A restart at 12:05 must not skip the day. Anything older than an
            # hour is left to the boot warm-up, which has its own staleness check.
            misfire_grace_time=3600,
        )

        # Elections board. Daily, for the ownership board's reason and one of
        # its own: the calendar upstream is a Wikipedia article edited when a
        # date is announced, so an interval would re-read the same page all day.
        #
        # The odds half is cached for fifteen minutes and would refresh itself
        # on demand, but it is warmed here anyway — the Gamma events payload is
        # about 4MB, and a user should never be the one waiting for it.
        #
        # Unlike the ownership job above, the timezone is a literal: 05:00 is
        # chosen as a quiet hour, not as a business hour somewhere, so there is
        # nothing here to localise.
        async def elections_refresh_job():
            try:
                from services.elections.service import fetch_elections

                board = await fetch_elections()
                log_success(
                    f"Elections refresh: {len(board['elections'])} scheduled, "
                    f"odds {'available' if board['odds_available'] else 'unavailable'}"
                )
            except Exception as e:
                log_error(f"Elections refresh error: {e}")

        scheduler.add_job(
            elections_refresh_job,
            trigger=CronTrigger(hour=settings.ELECTIONS_REFRESH_HOUR, minute=0, timezone="UTC"),
            id="elections_refresh_job",
            name="Refresh Elections Board",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            # A restart inside the hour must not skip the day.
            misfire_grace_time=3600,
        )

        # The live half of the board, on an interval. Only the sources that
        # change between two daily runs are asked; everything else is carried
        # forward from the last full build, so this costs three coin-table
        # requests and a handful of wallet reads rather than a whole rebuild.
        if settings.OWNERSHIP_LIVE_REFRESH_MINUTES > 0:

            async def ownership_live_refresh_job():
                try:
                    from services.ownership.refresh import LIVE_KINDS, refresh_ownership

                    report = await refresh_ownership(only_kinds=LIVE_KINDS)
                    log_step(
                        "🔄",
                        "Ownership live refresh: "
                        f"{report.entities_ok}/{report.entities_total} entities, "
                        f"{report.moves_new} new moves",
                    )
                except Exception as e:
                    log_error(f"Ownership live refresh error: {e}")

            scheduler.add_job(
                ownership_live_refresh_job,
                trigger=IntervalTrigger(minutes=settings.OWNERSHIP_LIVE_REFRESH_MINUTES),
                id="ownership_live_refresh_job",
                name="Refresh Live Ownership Sources",
                replace_existing=True,
                # Same reason as the daily job: the upstreams are paced, and two
                # concurrent runs would double the rate one of them is respecting.
                max_instances=1,
                coalesce=True,
            )

        scheduler.start()
        log_header("SCHEDULER STARTED")
        log_success(
            "Background tasks initialized "
            f"(News fetch: every {settings.NEWS_FETCH_INTERVAL_MINUTES}m, "
            f"RAG index: every {settings.RAG_INDEX_INTERVAL_MINUTES}m, "
            f"Heatmap: every {settings.HEATMAP_REFRESH_INTERVAL_MINUTES}m, "
            f"Ownership: daily at {settings.OWNERSHIP_REFRESH_HOUR:02d}:00 "
            f"{settings.OWNERSHIP_REFRESH_TIMEZONE})"
        )


def stop_scheduler():
    """Stop the background scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler shut down successfully.")
