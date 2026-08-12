"""
Symbol Detection Service — which tradeable asset a piece of text is about.

Attribution decides what the dashboard charts and what the analyser is told the
news concerns, so a wrong answer is worse than no answer: it renders an
unrelated price series and hands the model an asset the story never mentioned.
The pipeline is therefore built around one rule — **no ticker leaves this module
without being confirmed against a live listing**:

    1. explicit market notation in the headline ($AAPL, BTC/USDT)
    2. the LLM, which reads the text and may legitimately answer "no asset"
    3. name matching, but only when the LLM could not be reached at all

Crypto and equities are equal citizens. A story is not "a crypto story" because
it arrived on a crypto feed — CoinDesk covers Coinbase earnings, MarketWatch
covers bitcoin ETFs — so the asset class is derived from the symbol that was
actually resolved, and the feed's own class is only the tie-break hint.
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional, Tuple

from config import settings
from services import asset_registry
from services.ai_service import (
    SYMBOL_DETECTION_TIMEOUT_S,
    SymbolVerdict,
    detect_asset_symbol,
)
from services.cache import ServiceCache

logger = logging.getLogger(__name__)

CRYPTO_EXCHANGES = frozenset({"BINANCE", "OKX"})
EQUITY_EXCHANGES = frozenset({"NASDAQ", "NYSE"})


@dataclass(frozen=True)
class Attribution:
    """
    What a news item was found to be about.

    `confident` is False when the answer came out of a degraded path — the LLM
    could not be reached and the name matcher had the last word. The attribution
    is still the best available and is used as-is, but it is worth revisiting
    once a model can read the item, so the cache does not treat it as settled.
    """

    symbol: Optional[str]
    asset_type: str
    confident: bool = True


# Quote currencies and contract suffixes that may arrive attached to a base.
_QUOTE_SUFFIXES = ("USDT", "USDC", "USD", "PERP")

# Where to chart a coin when no exchange listing could be reached at all. Seven
# hand-maintained entries used to be the *only* exchange logic in this module,
# which is why anything Binance did not list charted as an invalid symbol; they
# now apply solely in that offline degraded mode.
OKX_PREFERRED_TOKENS = {
    "PI",
    "POPCAT",
    "BRETT",
    "MOG",
    "MEW",
    "WEN",
    "COQ",
}

# Coin/company names that are ordinary English or finance words. Every one of
# these is a real asset name — Rain, Sky, Cash, Gate, Core, Just, Kite, Block,
# Now, Net — and matching them on a bare mention is how "training data" became
# a RAIN headline and "ServiceNow" swallowed every sentence containing "now".
_AMBIGUOUS_NAMES = frozenset(
    # Asset names that are ordinary words
    "rain sky cash gate core just kite flow moon sun deep mask pump trump coco "
    "dash link block now net team snow coin unity square shop story wave boost "
    "grass myth vine beam step safe hive aster auto meta dear open next gold "
    "silver star "
    # Market vocabulary — a headline using these is describing the market, not
    # naming the company that happens to be called after it.
    "index market stock token chain swap nasdaq dow exchange trust fund invest "
    "trade future option "
    # Company names that are everyday nouns. Target Corp is a real company, but
    # "raises its target" is not a headline about it.
    "target match loop edge arrow pool range post wire bond share price rate "
    "money public signal rocket spark surge shift focus vision mission peak "
    "ridge sound light class board "
    # Generic corporate words, which head hundreds of listings apiece
    "prime first global capital united american national general advance alpha "
    "apex credit premier summit liberty heritage community citizens peoples "
    "home city state union allied associated consolidated universal superior "
    "select value quality service business commercial industrial financial "
    "investment income growth equity asset partners group holding enterprise "
    "ventures resources energy power health medical digital data cloud cyber "
    "smart micro west east north south bank banks banking western eastern "
    "northern southern central pacific atlantic standard royal empire legacy "
    "pioneer frontier horizon vista gateway bridge tower park".split()
)

# Name → current ticker, for the cases a listing lookup cannot cover: the coin's
# common name differs from its ticker, or the ticker itself was migrated. This
# is a *normalisation* table, not an asset list — every value still has to
# survive `resolve_crypto`, so a stale entry produces no attribution rather than
# a wrong one.
CRYPTO_ALIASES = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "ripple": "XRP",
    "xrpl": "XRP",
    "solana": "SOL",
    "cardano": "ADA",
    "dogecoin": "DOGE",
    "shiba inu": "SHIB",
    "polkadot": "DOT",
    "chainlink": "LINK",
    "litecoin": "LTC",
    "bitcoin cash": "BCH",
    "ethereum classic": "ETC",
    "stellar": "XLM",
    "vechain": "VET",
    "uniswap": "UNI",
    "cosmos": "ATOM",
    "algorand": "ALGO",
    "filecoin": "FIL",
    "tron": "TRX",
    "tezos": "XTZ",
    "zcash": "ZEC",
    "monero": "XMR",
    "internet computer": "ICP",
    "avalanche": "AVAX",
    # Polygon completed the MATIC → POL migration; MATIC no longer trades.
    "matic": "POL",
    "polygon": "POL",
    "the sandbox": "SAND",
    "decentraland": "MANA",
    "axie infinity": "AXS",
    "enjin coin": "ENJ",
    "chiliz": "CHZ",
    "compound": "COMP",
    "synthetix": "SNX",
    "yearn.finance": "YFI",
    "sushiswap": "SUSHI",
    "pancakeswap": "CAKE",
    "hyperliquid": "HYPE",
}

# Colloquial company names the exchange listing does not carry. The listing has
# "Alphabet Inc." and "Meta Platforms Inc.", not what people actually write.
EQUITY_ALIASES = {
    "google": "GOOGL",
    "facebook": "META",
    "instagram": "META",
    "whatsapp": "META",
    "youtube": "GOOGL",
    "microstrategy": "MSTR",
    "aws": "AMZN",
    "azure": "MSFT",
    "chatgpt": "MSFT",
    # Written as one word in headlines, two in the listing.
    "jpmorgan": "JPM",
    "goldman": "GS",
    "berkshire": "BRK.B",
    "walmart": "WMT",
    # AMEX is the company; AAME is Atlantic American, which a model reaching
    # for the nearest four-letter ticker will otherwise land on.
    "amex": "AXP",
}

# Tickers that are, in this app's copy, almost always an acronym rather than an
# asset. Each of these is a genuine listing — AI is Sleepless AI, US is a token,
# ETF is a ticker somewhere — but "AI infrastructure spending" is not a story
# about a coin, and a model asked for a symbol will reach for one anyway. They
# are only accepted when the author cashtagged them.
_ACRONYM_TICKERS = frozenset(
    {
        "AI",
        "US",
        "IT",
        "ID",
        "ME",
        "NOT",
        "GO",
        "ON",
        "UP",
        "NFT",
        "APR",
        "CEO",
        "ETF",
        "SEC",
        "CPI",
        "GDP",
        "IPO",
        "API",
        "EU",
        "UK",
        "FED",
        "DAO",
        "NFA",
    }
)

# Lookup tables derived from the registry, rebuilt on the registry's own TTL.
_lookup_cache = ServiceCache(maxsize=4)
_LOOKUP_TTL = 3600

# One ceiling for the whole process rather than per source: every feed is
# fetched concurrently, so without this the provider receives the entire
# refresh at once and times out on all of it.
_llm_gate = asyncio.Semaphore(settings.SYMBOL_DETECTION_CONCURRENCY)

# Wall-clock ceiling for the whole LLM attempt, across every provider the chain
# tries. Derived from the per-provider budget rather than hardcoded so the two
# can never drift into the state where this one is the smaller of the pair and
# silently disables the fallback chain.
SYMBOL_DETECTION_BUDGET_S = SYMBOL_DETECTION_TIMEOUT_S * 2.5


# ═══════════════════════════════════════════════════════════════════════════
# Resolution — the gate every candidate ticker passes through
# ═══════════════════════════════════════════════════════════════════════════


def _strip_quote(base: str) -> str:
    """`BTCUSDT` → `BTC`. Leaves a base that is itself a quote name alone."""
    base = base.upper()
    for suffix in _QUOTE_SUFFIXES:
        if base.endswith(suffix) and len(base) > len(suffix):
            return base[: -len(suffix)]
    return base


async def resolve_crypto(candidate: str) -> Optional[str]:
    """
    A confirmed crypto symbol in TradingView form, or None.

    The exchange comes from whichever venue actually lists the pair, so the
    symbol the browser is handed is one TradingView can draw.
    """
    base = _strip_quote(CRYPTO_ALIASES.get(candidate.lower().strip(), candidate).strip())
    if not base or not base.isalnum():
        return None
    # Everything here is quoted in USDT, so USDT itself has no pair. A Tether
    # story is real news; "USDTUSDT" is not a chart.
    if base == "USDT":
        return None

    exchange = await asset_registry.exchange_for_crypto(base)
    if exchange:
        return f"{exchange}:{base}USDT"

    # Not on any listing we could read. Only a coin the market-cap universe
    # knows gets the benefit of the doubt, and only while the listing that
    # would have settled it is missing.
    universe = {coin["symbol"] for coin in await asset_registry.get_crypto_universe()}
    if base not in universe:
        return None

    listed = await asset_registry.get_listed_bases() or {}
    if "BINANCE" in listed:
        # Every listing was readable and none carries it. There is no venue
        # left to guess at.
        return None

    # Binance is unreachable from some networks, so its listing may simply be
    # missing rather than negative. A coin large enough to be in the top 250 is
    # very likely to trade there; TradingView draws it from its own feed, which
    # is not subject to this machine's network.
    exchange = "OKX" if base in OKX_PREFERRED_TOKENS else "BINANCE"
    logger.debug("Binance listing unreadable — charting %s on %s unverified", base, exchange)
    return f"{exchange}:{base}USDT"


async def resolve_equity(ticker: str, exchange_hint: Optional[str] = None) -> Optional[str]:
    """A confirmed US equity symbol (`NASDAQ:AAPL`, `NYSE:JPM`), or None."""
    ticker = EQUITY_ALIASES.get(ticker.lower().strip(), ticker).strip().upper()
    if not ticker:
        return None

    exchange = await asset_registry.equity_exchange(ticker)
    if exchange:
        return f"{exchange}:{ticker}"

    if await asset_registry.get_us_equity_index() is None:
        # The listing could not be read from any layer, so "unknown ticker" and
        # "unknown listing" are indistinguishable. Keep the caller's exchange
        # rather than inventing one.
        if exchange_hint in EQUITY_EXCHANGES:
            logger.warning(
                "US equity listing unavailable — charting %s:%s unverified",
                exchange_hint,
                ticker,
            )
            return f"{exchange_hint}:{ticker}"
    return None


async def resolve(candidate: str, hint: str = "crypto") -> Optional[str]:
    """
    Confirm one candidate — `"BINANCE:BTCUSDT"`, `"AAPL"`, `"pepe"` — or None.

    Both asset classes are always tried. `hint` only decides which is tried
    first, because a bare ticker can exist in both worlds; an explicit exchange
    prefix on the candidate outranks it.
    """
    candidate = (candidate or "").strip().lstrip("$").strip()
    if not candidate:
        return None

    exchange, _, ticker = candidate.rpartition(":")
    exchange = exchange.upper()
    ticker = ticker.strip()
    if not ticker:
        return None

    if exchange in EQUITY_EXCHANGES:
        order = ("equity", "crypto")
    elif exchange in CRYPTO_EXCHANGES:
        order = ("crypto", "equity")
    else:
        order = ("crypto", "equity") if hint == "crypto" else ("equity", "crypto")

    for kind in order:
        if kind == "crypto":
            resolved = await resolve_crypto(ticker)
        else:
            resolved = await resolve_equity(ticker, exchange_hint=exchange or None)
        if resolved:
            return resolved
    return None


def asset_type_for_symbol(symbol: Optional[str], fallback: str = "crypto") -> str:
    """The asset class a resolved symbol belongs to."""
    if not symbol:
        return fallback
    exchange = symbol.split(":")[0].upper()
    if exchange in EQUITY_EXCHANGES:
        return "stock"
    if exchange in CRYPTO_EXCHANGES:
        return "crypto"
    return fallback


# ═══════════════════════════════════════════════════════════════════════════
# Strategy 1 — explicit market notation
# ═══════════════════════════════════════════════════════════════════════════

# $BTC, $AAPL — a cashtag is an author stating the subject outright.
_CASHTAG_RE = re.compile(r"\$([A-Za-z][A-Za-z0-9.]{1,9})\b")
# BTC/USDT, ETH/USD — a quoted pair, equally explicit.
_PAIR_RE = re.compile(r"\b([A-Za-z]{2,10})/(USDT|USDC|USD|BTC|ETH)\b", re.IGNORECASE)
# (NASDAQ: AAPL) — how wire copy tags the company it just named. The exchange
# is required: a bare "(AI)" is almost always an acronym being defined, and
# C3.ai really does trade as NYSE:AI.
_PAREN_TICKER_RE = re.compile(
    r"\(\s*(?:NASDAQ|NYSE(?:\s+Arca)?|AMEX)\s*:\s*([A-Z]{1,5})\s*\)", re.IGNORECASE
)


def find_pattern_matches(text: str) -> list[Tuple[str, str]]:
    """
    Candidate tickers written in explicit market notation, most explicit first.

    Returns `(ticker, notation)` pairs. Only notation an author uses
    deliberately counts. Bare uppercase words do not: "US inflation cools" is
    not a headline about a token called US.
    """
    candidates: list[Tuple[str, str]] = []
    for match in _CASHTAG_RE.finditer(text):
        candidates.append((match.group(1).upper(), "cashtag"))
    for match in _PAIR_RE.finditer(text):
        candidates.append((match.group(1).upper(), "pair"))
    for match in _PAREN_TICKER_RE.finditer(text):
        candidates.append((match.group(1).upper(), "tagged"))
    return candidates


# ═══════════════════════════════════════════════════════════════════════════
# Strategy 3 — name matching, for when the LLM cannot be reached
# ═══════════════════════════════════════════════════════════════════════════

# Corporate and industry boilerplate. Stripped from both the listing name and
# the headline, so the two still line up: "Sensient Technologies" in the table
# and "Sensient Technologies stock" in a headline both reduce to "sensient".
# Without this, a company whose whole distinctive name is an industry word —
# International Bancshares — claims that word, and every headline mentioning
# any bancshares matches it.
_COMPANY_SUFFIX_RE = re.compile(
    r"\b(inc|corp|corporation|co|company|ltd|limited|plc|holdings?|group|"
    r"technologies|technology|systems|solutions|international|industries|"
    r"enterprises|labs?|nv|sa|ag|se|the|bancshares|bancorp|financial|"
    r"communications|pharmaceuticals?|therapeutics|laboratories|brands|"
    r"motors|airlines|resources|properties|realty|stores|foods|media|"
    r"entertainment|networks|semiconductors?)\b\.?",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")


def _normalise_name(raw: str) -> str:
    """Company/coin name reduced to its brand words."""
    name = _COMPANY_SUFFIX_RE.sub(" ", raw.lower())
    name = _PUNCT_RE.sub(" ", name)
    return " ".join(name.split())


# How many companies the name matcher considers, by market cap. The listing
# itself runs to ~6000 symbols, and its tail is full of names that are ordinary
# words in a headline — Credit Acceptance Corp turning "Credit Suisse pursuit"
# into a stock tip. News is about larger companies; the tail only adds noise.
#
# Measured against a set of headlines that name a company and a set that only
# appear to: 500 catches 2 of 7 real mentions, 1500 catches 4, and both are
# clean. 3000 catches 5 but starts turning "oil prices climb" into CLYM and
# "the housing crisis" into UAA, which is the failure this whole module exists
# to prevent. Re-measure before changing it.
_NAME_MATCH_COMPANIES = 1500


def _index_name(
    table: dict[str, Tuple[str, int, float]],
    key: str,
    ticker: str,
    weight: float,
    exact: bool = True,
) -> None:
    """
    Record a name → ticker mapping, keeping the best claim when two collide.

    Both Apple Inc. and Apple Hospitality REIT answer to "Apple". Dropping the
    key would lose the company every headline actually means, so the asset whose
    *whole* name is the key wins first, and size breaks the remaining ties.
    """
    if len(key) < 4 or key in _AMBIGUOUS_NAMES:
        return
    rank = (1 if exact else 0, weight)
    existing = table.get(key)
    if existing is None or rank > (existing[1], existing[2]):
        table[key] = (ticker, rank[0], weight)


# Share classes that are not what a headline means by a company's name.
_NON_COMMON_SHARE_RE = re.compile(
    r"\b(preferred|warrant|depositary|debenture|note|unit|right|subordinated|"
    r"perpetual|convertible)s?\b",
    re.IGNORECASE,
)


async def _crypto_name_table() -> dict[str, Tuple[str, int, float]]:
    """Coin name → ticker, built from the live market-cap universe."""
    cached = _lookup_cache.get("crypto_names")
    if cached is not None:
        return cached

    universe = await asset_registry.get_crypto_universe()
    table: dict[str, Tuple[str, int, float]] = {}
    for coin in universe:
        name = _normalise_name(coin["name"])
        if name:
            _index_name(table, name, coin["symbol"], float(coin.get("market_cap") or 0))
    # Aliases outrank listing names: they are curated, and "bitcoin" must never
    # lose to some coin that registered "Bitcoin" as part of its own name.
    for alias, ticker in CRYPTO_ALIASES.items():
        _index_name(table, alias, ticker, float("inf"))

    _lookup_cache.set("crypto_names", table, _LOOKUP_TTL)
    return table


async def _equity_name_table() -> dict[str, Tuple[str, int, float]]:
    """Company name → ticker, built from the NASDAQ and NYSE listings."""
    cached = _lookup_cache.get("equity_names")
    if cached is not None:
        return cached

    index = await asset_registry.get_us_equity_index() or {}
    largest = sorted(index.items(), key=lambda row: row[1].get("market_cap") or 0, reverse=True)[
        :_NAME_MATCH_COMPANIES
    ]

    table: dict[str, Tuple[str, int, float]] = {}
    for ticker, record in largest:
        if _NON_COMMON_SHARE_RE.search(record["name"]):
            continue
        name = _normalise_name(record["name"])
        if not name:
            continue
        weight = float(record.get("market_cap") or 0)
        _index_name(table, name, ticker, weight)
        # Companies are written by their first word far more often than by
        # their registered name — "Tesla", not "Tesla Inc".
        head = name.split()[0]
        if head != name:
            _index_name(table, head, ticker, weight, exact=False)
    for alias, ticker in EQUITY_ALIASES.items():
        _index_name(table, alias, ticker, float("inf"))

    _lookup_cache.set("equity_names", table, _LOOKUP_TTL)
    return table


def _lookup_ngrams(
    title: str,
    table: dict[str, Tuple[str, int, float]],
    first_only: bool = True,
    exact_only: bool = False,
) -> list[str]:
    """
    Tickers whose names appear in the title, longest name first.

    Word n-grams rather than substring search: "Sui" must not match "Credit
    Suisse", and "Rain" must not match "training".

    `exact_only` keeps just the assets whose *whole* name is in the headline,
    dropping the first-word matches that let "Tesla" stand for Tesla Inc. Those
    are useful evidence when there is none better, and much too weak to
    overturn a decision made by something that read the article: "Community
    West Bancshares" contains the first word of West Pharmaceutical.
    """
    words = _normalise_name(title).split()
    found: list[str] = []
    for size in (3, 2, 1):
        for start in range(len(words) - size + 1):
            entry = table.get(" ".join(words[start : start + size]))
            if not entry or (exact_only and not entry[1]):
                continue
            if entry[0] not in found:
                found.append(entry[0])
                if first_only:
                    return found
    return found


async def _match_by_name(title: str, hint: str) -> Optional[str]:
    """Resolve a headline by the asset names it spells out."""
    tables = (
        (_crypto_name_table, resolve_crypto)
        if hint == "crypto"
        else (_equity_name_table, resolve_equity)
    )
    other = (
        (_equity_name_table, resolve_equity)
        if hint == "crypto"
        else (_crypto_name_table, resolve_crypto)
    )

    for build_table, resolve_fn in (tables, other):
        for ticker in _lookup_ngrams(title, await build_table()):
            resolved = await resolve_fn(ticker)
            if resolved:
                return resolved
    return None


async def _names_in_title(title: str) -> list[Tuple[str, str]]:
    """
    Every asset named outright, in full, in the headline.

    Returns `(ticker, kind)` pairs — the table a name came from already says
    which asset class it is, so nothing has to be guessed back out of it.
    """
    crypto = _lookup_ngrams(title, await _crypto_name_table(), first_only=False, exact_only=True)
    equity = _lookup_ngrams(title, await _equity_name_table(), first_only=False, exact_only=True)
    return [(t, "crypto") for t in crypto] + [(t, "equity") for t in equity]


async def _corrected_by_name(candidate: str, title: str) -> Optional[str]:
    """
    A ticker the headline actually names, when the model picked a different one.

    Models reach for near-miss tickers: "Sensient Technologies stock surging"
    came back as SNN (Smith & Nephew) rather than SXT. The exchange listing
    says which company "Sensient" is, and that is harder evidence than recall.

    The correction only applies when the model's own ticker is named nowhere in
    the headline. A story that names two companies — "JPMorgan raises its
    target for Nvidia" — must keep the model's choice of which one it is about,
    since the headline names both and only the model read the article.
    """
    named = await _names_in_title(title)
    if not named:
        return None

    _, _, ticker = candidate.rpartition(":")
    ticker = _strip_quote(ticker.strip().upper())
    if any(alternative == ticker for alternative, _kind in named):
        return None

    for alternative, kind in named:
        resolved = (
            await resolve_crypto(alternative)
            if kind == "crypto"
            else await resolve_equity(alternative)
        )
        if resolved:
            return resolved
    return None


# ═══════════════════════════════════════════════════════════════════════════
# Detection
# ═══════════════════════════════════════════════════════════════════════════


def is_uncashtagged_acronym(candidate: str, title: str) -> bool:
    """
    True when the proposed ticker only reads as a ticker to a machine.

    "MEXC expands offerings with AI infrastructure" is not a story about
    Sleepless AI, and "US inflation cools" is not about a token called US — but
    anything asked to name a symbol will produce one. Tree of Alpha's own
    tagger makes this mistake as readily as a model does, so its tags go
    through here too. Requiring the cashtag keeps the genuine mentions, which
    is how these tickers are actually written.
    """
    _, _, ticker = candidate.rpartition(":")
    ticker = _strip_quote(ticker.strip().upper())
    if ticker not in _ACRONYM_TICKERS:
        return False
    return not any(
        found == ticker for found, notation in find_pattern_matches(title) if notation == "cashtag"
    )


async def _ask_llm(title: str, text: str, asset_type: str) -> SymbolVerdict:
    """
    The model's reading of the item, under a concurrency and time ceiling.

    A timeout is reported as `answered=False` so the caller falls back rather
    than treating silence as "no asset". The budget has to exceed one provider's
    own timeout, or this cancels the call before the LLM layer can try the next
    provider in the chain.
    """
    llm_context = f"{title}\n{text[:300]}"
    try:
        async with _llm_gate:
            return await asyncio.wait_for(
                detect_asset_symbol(llm_context, asset_type=asset_type),
                timeout=SYMBOL_DETECTION_BUDGET_S,
            )
    except TimeoutError:
        # Logged with the budget spelled out because TimeoutError stringifies
        # to nothing, which used to surface as a bare "LLM failed:".
        logger.warning(
            "[SymbolDetection] No LLM answer within %.0fs — using heuristics instead. "
            "A local model still loading into memory is the usual cause.",
            SYMBOL_DETECTION_BUDGET_S,
        )
    except Exception as e:
        logger.error("[SymbolDetection] LLM failed: %s: %s", type(e).__name__, e)
    return SymbolVerdict(symbol=None, answered=False)


async def detect_symbol_smart(
    text: str,
    title: str = "",
    asset_type: str = "crypto",
) -> Attribution:
    """
    Work out which asset a news item is about.

    The symbol carried back is a confirmed TradingView symbol or None, and the
    asset class is derived from it rather than from the feed it arrived on — a
    crypto desk covering Coinbase earnings is reporting on a stock.

    None is a real answer, not a failure. Plenty of market news — rate
    decisions, index recaps, regulatory colour — is about no single tradeable
    asset, and filing it under one charts it against a price it has nothing to
    do with.
    """
    hint = asset_type if asset_type in ("crypto", "stock") else "crypto"

    # Strategy 1: explicit notation in the headline. Restricted to the title on
    # purpose — a cashtag buried in a summary is usually a passing comparison,
    # not the subject.
    for candidate, _notation in find_pattern_matches(title):
        resolved = await resolve(candidate, hint)
        if resolved:
            return Attribution(resolved, asset_type_for_symbol(resolved, hint))

    # Strategy 2: the model reads the item.
    verdict = await _ask_llm(title, text, hint)
    if verdict.answered:
        if not verdict.symbol:
            # The model read it and found no tradeable subject. That is the
            # answer; the name matcher below must not overrule it.
            return Attribution(None, hint)
        if is_uncashtagged_acronym(verdict.symbol, title):
            logger.info(
                "[SymbolDetection] %s reads as an acronym here, not a ticker — unattributed",
                verdict.symbol,
            )
            return Attribution(None, hint)
        corrected = await _corrected_by_name(verdict.symbol, title)
        if corrected:
            logger.info(
                "[SymbolDetection] LLM said %s but the headline names %s",
                verdict.symbol,
                corrected,
            )
            return Attribution(corrected, asset_type_for_symbol(corrected, hint))

        resolved = await resolve(verdict.symbol, hint)
        if resolved:
            logger.info("[SymbolDetection] LLM found: %s", resolved)
            return Attribution(resolved, asset_type_for_symbol(resolved, hint))
        logger.info(
            "[SymbolDetection] LLM answer %s is not a listed asset — unattributed",
            verdict.symbol,
        )
        return Attribution(None, hint)

    # Strategy 3: no answer from any provider. Fall back to the names the
    # headline spells out — never to bare tickers, which collide with ordinary
    # words far too often to be evidence of anything.
    resolved = await _match_by_name(title, hint)
    if resolved:
        logger.info("[SymbolDetection] Name match: %s", resolved)
        return Attribution(resolved, asset_type_for_symbol(resolved, hint), confident=False)

    return Attribution(None, hint, confident=False)
