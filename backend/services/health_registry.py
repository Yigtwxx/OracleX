"""
Health Registry
Tracks, per data-source category, whether the last upstream call worked.

Passive by design. Nothing here reaches out to a provider — the shared HTTP
helpers, the exchange client, the websocket feed and the database wrapper each
report what they already did, and this module only remembers it. That keeps the
badge honest (it reflects the traffic the app actually makes) and costs no rate
limit of its own.

The trade-off is that a category nobody has called yet has no verdict. It is
reported as `idle` rather than guessed at, and the badge treats idle as "not a
problem" — the alternative, probing on a timer, would spend quota to answer a
question no user is asking.

The same reasoning applies once a category goes quiet again: a long silence is
reported as `stale`, which is shown but never counted as a fault. Only a call
that actually failed can turn the badge yellow or red. Categories that are only
called when a user asks for them — the LLM chain, the database — opt out of
staleness entirely, because there silence means nobody asked.

State is per-process and in memory. A restart resets it, which is correct: a
verdict about a provider from before the restart says nothing about now.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

# ── Categories ──────────────────────────────────────────────────────────────
#
# Grouped by what the user would lose, not by hostname. "CoinGecko is down" is
# only meaningful to someone who knows what reads it; "Crypto Prices degraded"
# is meaningful to everyone. `critical` marks the categories whose loss makes
# the app wrong rather than merely thinner — those are what turn the badge red.


# How long a polled category may stay silent before the panel stops vouching
# for its last success. Generous, because the slowest categories are polled on a
# fifteen-minute schedule and a row that greys out between two healthy refreshes
# is worse than no row at all.
STALE_AFTER_S = 30 * 60


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    critical: bool
    providers: tuple[str, ...]
    # Seconds of silence after which the category reads as `stale`, or None to
    # never go stale. None is for the demand-driven categories: nothing polls
    # them, so their age measures how long since a user last needed them.
    stale_after_s: Optional[float] = STALE_AFTER_S


CATEGORIES: tuple[Category, ...] = (
    Category(
        "prices_crypto",
        "Crypto Prices",
        True,
        ("Binance", "OKX", "Bybit", "CoinGecko", "Kraken"),
    ),
    Category("stream", "Live Stream", True, ("Price websocket",)),
    Category("database", "Database", True, ("Supabase",), stale_after_s=None),
    Category("stocks", "Stocks", False, ("Yahoo Finance", "Nasdaq", "FMP")),
    Category("news", "News", False, ("Investing", "CoinDesk", "TreeOfAlpha", "RSS feeds")),
    Category(
        "onchain",
        "On-chain",
        False,
        (
            "mempool.space",
            "LlamaRPC",
            "DefiLlama",
            "Blockscout",
            "Coin Metrics",
            "publicnode",
            "Base RPC",
            "Arbitrum RPC",
            "OP Mainnet RPC",
            "Solana RPC",
            "TronGrid",
        ),
    ),
    Category(
        "macro",
        "Macro & Sentiment",
        False,
        (
            "Federal Reserve",
            "CNN Fear & Greed",
            "TradingView Calendar",
            "ForexFactory",
            "PizzINT",
            "Wikipedia",
            "Resmî Gazete",
            "Cumhurbaşkanlığı",
        ),
    ),
    Category("ai", "AI / LLM", False, ("Local LLM chain",), stale_after_s=None),
    # Prediction markets get their own category rather than folding into macro,
    # which is the opposite call to the one made for PizzINT a few lines up and
    # for the same reason. Losing PizzINT costs one gauge on a board that still
    # works; losing these three hosts costs the Polymarket tab entirely — the
    # board, the map and the bet analysis all read from them. A category is
    # meant to name what a user would lose, and here that is a whole surface.
    Category(
        "prediction",
        "Prediction Markets",
        False,
        ("Polymarket Gamma", "Polymarket CLOB", "Polymarket Data"),
    ),
    # Outbound alarm mail. `stale_after_s=None` because nothing polls the relay
    # — the age of this row measures how long since an alarm actually needed to
    # send, and a quiet week is not a fault. Not critical: a dead relay costs
    # one delivery channel while the toast, the sound and the OS notification
    # all still fire.
    Category("notifications", "Notifications", False, ("SMTP relay",), stale_after_s=None),
    # Borsa İstanbul's surface. Its own category rather than folded into
    # `stocks` because the two lose different things: `stocks` is the US board,
    # and every host below serves a page that has no US equivalent — a fund
    # platform, a disclosure archive, a central bank series. A TEFAS outage
    # costs the entire Fonlar tab while the US board is untouched, and the
    # badge should say so.
    #
    # Yahoo is deliberately absent from this list even though BIST quotes come
    # from it. It is already named under `stocks`, and one upstream reported in
    # two categories would show as two independent failures when it broke.
    Category(
        "bist",
        "BIST & TEFAS",
        False,
        ("TEFAS", "KAP", "Borsa İstanbul", "Takasbank", "TCMB"),
    ),
)

_BY_KEY = {c.key: c for c in CATEGORIES}

# Hostname suffix → category. Matched longest-first so a specific subdomain can
# override the registrable domain above it.
_HOST_MAP: dict[str, str] = {
    # Crypto prices
    "binance.com": "prices_crypto",
    "okx.com": "prices_crypto",
    "bybit.com": "prices_crypto",
    "kraken.com": "prices_crypto",
    "kucoin.com": "prices_crypto",
    "gate.io": "prices_crypto",
    "huobi.com": "prices_crypto",
    "coinbase.com": "prices_crypto",
    "api.coingecko.com": "prices_crypto",
    "pro-api.coingecko.com": "prices_crypto",
    # Derivatives statistics for the open-interest board. It reads the same
    # three exchanges the entries above name, so a Coinalyze outage costs the
    # board its depth and nothing else in this category.
    "api.coinalyze.net": "prices_crypto",
    # Macro. The specific subdomain rather than wikipedia.org, following the
    # Polymarket hosts below: the API is the only Wikimedia surface this app
    # touches, and a wildcard would silently adopt any future one.
    "en.wikipedia.org": "macro",
    # Stocks
    "finance.yahoo.com": "stocks",
    "query1.finance.yahoo.com": "stocks",
    "query2.finance.yahoo.com": "stocks",
    "fc.yahoo.com": "stocks",
    "api.nasdaq.com": "stocks",
    "financialmodelingprep.com": "stocks",
    # Borsa İstanbul. Mapped by registrable domain: TEFAS fronts both
    # `www.tefas.gov.tr` and the bare host, and KAP moved to a Next.js app whose
    # API subdomain has changed once already.
    "tefas.gov.tr": "bist",
    "kap.org.tr": "bist",
    "borsaistanbul.com": "bist",
    # The clearing house, for the margin scan ranges the VİOP map draws its
    # bands at. A separate host from the exchange and a separate outage.
    "takasbank.com.tr": "bist",
    "isyatirim.com.tr": "bist",
    # The equity board's quote source. The specific subdomain, not
    # tradingview.com: the economic calendar above is a different host on the
    # same domain and belongs to `macro`, and a bare suffix here would swallow
    # it — longest-suffix-first matching means the more specific entry wins,
    # but only if both are spelled out.
    "scanner.tradingview.com": "bist",
    # The central bank's statistical service — policy rate, CPI, USDTRY. The
    # specific host rather than tcmb.gov.tr, which also serves the public site.
    "evds3.tcmb.gov.tr": "bist",
    # On-chain
    "mempool.space": "onchain",
    "llamarpc.com": "onchain",
    "llama.fi": "onchain",
    "publicnode.com": "onchain",
    "blockscout.com": "onchain",
    "coinmetrics.io": "onchain",
    # The Chains board's own nodes. Every one of these is a public RPC endpoint
    # for a single chain, so they are the same kind of dependency as the three
    # above and lose the same thing when they fail — one column of the board,
    # not the app. Mapped by registrable domain because each vendor fronts
    # several subdomains (arb1./nova., mainnet./sepolia.) and the suffix match
    # is what keeps this list from having to track them.
    "base.org": "onchain",
    "arbitrum.io": "onchain",
    "optimism.io": "onchain",
    "solana.com": "onchain",
    "trongrid.io": "onchain",
    # BSC's fallback seed node. Named `binance.org` rather than treated as an
    # exchange host: this serves chain state, not the trading API, and a failure
    # here costs the BNB Chain row rather than any price.
    "binance.org": "onchain",
    # Macro & sentiment
    "federalreserve.gov": "macro",
    "dataviz.cnn.io": "macro",
    "economic-calendar.tradingview.com": "macro",
    "faireconomy.media": "macro",
    # The Pentagon Pizza Index's upstream. Grouped with macro & sentiment rather
    # than given a category of its own: losing it costs one novelty gauge on the
    # macro board, which is the same shape of loss as losing the Fear & Greed
    # feed beside it.
    "pizzint.watch": "macro",
    # The Gece Mesaisi Endeksi's two sources. Filed under `macro` beside
    # PizzINT rather than under `bist`, by that category's own rule: losing
    # these costs one novelty gauge in the chrome, while every host under
    # `bist` costs a whole tab.
    "resmigazete.gov.tr": "macro",
    "tccb.gov.tr": "macro",
    # Everything editorial. Listed rather than defaulted so an unmapped host is
    # visible as unmapped instead of quietly inflating the news category.
    "investing.com": "news",
    "coindesk.com": "news",
    "theblock.co": "news",
    "cryptoslate.com": "news",
    "decrypt.co": "news",
    "seekingalpha.com": "news",
    "treeofalpha.com": "news",
    "dowjones.io": "news",
    "koinbulteni.com": "news",
    "uzmancoin.com": "news",
    # Prediction markets. Three hosts with one owner but genuinely separate
    # roles — discovery, pricing and trade history — so all three are listed
    # rather than mapped off the registrable domain: a CLOB outage with Gamma
    # healthy is a board that renders without live odds, and the badge should
    # be able to say so.
    "gamma-api.polymarket.com": "prediction",
    "clob.polymarket.com": "prediction",
    "data-api.polymarket.com": "prediction",
    "polymarket.com": "prediction",
}

# Consecutive failures before a category is reported as down rather than merely
# degraded. One failure is usually a blip; three in a row is an outage.
#
# Only failures that suggest the provider is actually unavailable are counted.
# A category is a group of providers behind one verdict, so its worst upstream
# must not be able to speak for the rest of them — see `_Source`.
DOWN_AFTER_FAILURES = 3


def category_for_url(url: str) -> Optional[str]:
    """Map an upstream URL to a category key, or None if the host is unmapped."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return None
    if not host:
        return None
    # Longest suffix wins: "query1.finance.yahoo.com" before "yahoo.com".
    for suffix in sorted(_HOST_MAP, key=len, reverse=True):
        if host == suffix or host.endswith("." + suffix):
            return _HOST_MAP[suffix]
    return None


def _status_code(error: BaseException) -> Optional[int]:
    """The HTTP status an exception carries, whichever way it carries it."""
    status = getattr(getattr(error, "response", None), "status_code", None)
    if status is None:
        status = getattr(error, "status_code", None)
    return status if isinstance(status, int) else None


def is_rate_limited(error: Optional[BaseException]) -> bool:
    """
    True when a failure is a quota refusal rather than an unavailable provider.

    A 429 says the upstream is healthy and we asked too often — on the free
    CoinGecko tier that is routine, and it says nothing about the four exchanges
    sharing that category. Counting it towards an outage is what let one
    throttled provider report the whole category, and the app, as offline.
    """
    return error is not None and _status_code(error) == 429


def summarize_error(error: BaseException) -> str:
    """
    Reduce an exception to a short, non-identifying reason.

    The panel is public, so nothing here may leak a URL, a host, a query string
    or a token — an upstream's own error body routinely contains all four. The
    caller gets a category of failure, which is all the badge needs to explain
    itself.
    """
    name = type(error).__name__
    status = _status_code(error)

    if isinstance(status, int):
        if status == 429:
            return "rate limited (429)"
        if status in (401, 403):
            return "auth failed"
        if status >= 500:
            return f"upstream error ({status})"
        return f"rejected ({status})"

    lowered = name.lower()
    if "timeout" in lowered:
        return "timeout"
    if "connect" in lowered:
        return "unreachable"
    return "request failed"


@dataclass
class _Source:
    """
    Rolling verdict for one category.

    Two failure counters, because a category speaks for several providers at
    once. `consecutive_failures` is what the panel reports — any recent failure
    is worth showing. `consecutive_outage_failures` is the stricter one that can
    turn the badge red, and it ignores quota refusals: a rate-limited CoinGecko
    means the Crypto Prices board is thinner, not that Binance, OKX, Bybit and
    Kraken stopped answering.
    """

    last_ok_at: Optional[float] = None
    last_failure_at: Optional[float] = None
    last_latency_ms: Optional[int] = None
    last_error: Optional[str] = None
    consecutive_failures: int = 0
    consecutive_outage_failures: int = 0

    def state(self, now: float, stale_after: Optional[float] = STALE_AFTER_S) -> str:
        if self.consecutive_outage_failures >= DOWN_AFTER_FAILURES:
            return "down"
        if self.consecutive_failures:
            # Including the case where nothing has succeeded yet. A category
            # that failed on the way up is warming up badly, which is worth a
            # yellow light — but calling it an outage on the first attempt made
            # a single 429 during boot report the whole app as offline.
            return "degraded"
        if self.last_ok_at is None:
            return "idle"
        if stale_after is not None and now - self.last_ok_at > stale_after:
            # Old news, not bad news. Reported separately so the badge can stay
            # green: nothing failed here, the category simply has not been
            # exercised recently, and calling that `degraded` made a quiet
            # afternoon look like an incident.
            return "stale"
        return "ok"


@dataclass
class HealthRegistry:
    """In-memory health of every data-source category. Not thread-safe by
    design — every writer runs on the single asyncio loop, and the only
    operations are whole-field assignments."""

    _sources: dict[str, _Source] = field(
        default_factory=lambda: {c.key: _Source() for c in CATEGORIES}
    )

    def record(
        self,
        category: Optional[str],
        *,
        ok: bool,
        latency_ms: Optional[int] = None,
        error: Optional[BaseException] = None,
    ) -> None:
        """Note the outcome of one upstream call. Unmapped categories are dropped."""
        source = self._sources.get(category or "")
        if source is None:
            return

        now = time.time()
        if ok:
            source.last_ok_at = now
            source.last_latency_ms = latency_ms
            source.last_error = None
            source.consecutive_failures = 0
            source.consecutive_outage_failures = 0
        else:
            source.last_failure_at = now
            source.consecutive_failures += 1
            if not is_rate_limited(error):
                source.consecutive_outage_failures += 1
            source.last_error = summarize_error(error) if error else "request failed"

    def record_url(
        self,
        url: str,
        *,
        ok: bool,
        latency_ms: Optional[int] = None,
        error: Optional[BaseException] = None,
    ) -> None:
        """`record`, with the category derived from the URL's host."""
        self.record(category_for_url(url), ok=ok, latency_ms=latency_ms, error=error)

    def reset(self) -> None:
        """Forget every verdict. For tests."""
        self._sources = {c.key: _Source() for c in CATEGORIES}

    def snapshot(self) -> dict:
        """
        The whole board, as the badge endpoint returns it.

        Pure reads of in-memory state: the frontend polls this every ten seconds
        and must never pay for I/O to get it.
        """
        now = time.time()
        rows = []
        for category in CATEGORIES:
            source = self._sources[category.key]
            state = source.state(now, category.stale_after_s)
            rows.append(
                {
                    "key": category.key,
                    "label": category.label,
                    "critical": category.critical,
                    "providers": list(category.providers),
                    "state": state,
                    "last_ok_at": source.last_ok_at,
                    "latency_ms": source.last_latency_ms,
                    "detail": source.last_error if state in ("degraded", "down") else None,
                }
            )

        return {
            "status": _overall(rows),
            "generated_at": now,
            "categories": rows,
        }


def _overall(rows: list[dict]) -> str:
    """
    Collapse the board into the one word on the badge.

    `idle` and `stale` never degrade the verdict — a category nobody has called
    yet, or has not called lately, is not evidence of a fault; only a call that
    failed is. A build where every category is idle reports `starting`, which is
    what the frontend shows before the first data lands.
    """
    if any(r["critical"] and r["state"] == "down" for r in rows):
        return "offline"
    if any(r["state"] in ("down", "degraded") for r in rows):
        return "degraded"
    if all(r["state"] == "idle" for r in rows):
        return "starting"
    return "live"


health = HealthRegistry()


def is_known_category(key: str) -> bool:
    """True if `key` names a category the registry tracks."""
    return key in _BY_KEY
