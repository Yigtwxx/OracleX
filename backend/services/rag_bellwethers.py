"""
Bellwether universe — the assets whose history is worth learning from.

Historical precedent is only useful when it comes from something that moves the
rest of the market. Measuring the multi-horizon outcome of an event is not free
(a year of candles per event, from OKX or Yahoo), so it is spent on the assets
that set direction rather than on every listed symbol.

The pay-off is spillover: a lesson learned from a bellwether applies to the
assets that follow it. A regulatory shock to XRP tells you something about the
next altcoin sued; a memory-pricing shock to MU tells you something about the
next semiconductor. `rag_scoring.symbol_weight` is what turns that into a
number — a bellwether's precedent keeps most of its weight when the question is
about a smaller asset, instead of being penalised as a symbol mismatch.

The lists are hand-curated from index weights and dominance data measured on
2026-07-22 (see the `rag-bellwether-universe` project note for sources). Index
membership drifts and weights rebalance quarterly, so this file is expected to
be revisited, not to be right forever.
"""

from typing import FrozenSet, List, Optional, Tuple

# ═══════════════════════════════════════════════════════════════════════════════
# CRYPTO
# ═══════════════════════════════════════════════════════════════════════════════

# BTC dominance sat in the 54-57% band through 2026 with the Altcoin Season
# Index at 37 — firmly "Bitcoin season", where alts track BTC rather than
# decoupling from it. So BTC is not merely the largest asset, it is the one
# whose moves propagate.
CRYPTO_PRIMARY: Tuple[str, ...] = ("BTC",)

# ETH is the rotation signal: the ETH/BTC ratio is what turns first when capital
# starts moving down the risk curve into alts.
CRYPTO_SECONDARY: Tuple[str, ...] = ("ETH",)

# Large enough to have their own event history worth indexing, but they follow
# BTC more than they lead. XRP earns its place on regulatory history alone.
CRYPTO_MAJORS: Tuple[str, ...] = ("XRP", "SOL", "BNB", "DOGE", "ADA")

CRYPTO_BELLWETHERS: Tuple[str, ...] = CRYPTO_PRIMARY + CRYPTO_SECONDARY + CRYPTO_MAJORS


# ═══════════════════════════════════════════════════════════════════════════════
# EQUITIES
# ═══════════════════════════════════════════════════════════════════════════════

# The Nasdaq-100's top ten by weight, ~45% of the index between them. Note this
# is not the "Magnificent Seven": on 2026-07-22 Micron (4.82%) and AMD (4.02%)
# both outweighed Microsoft (4.68% / 4.25% for Amazon), and assuming the classic
# seven would have missed the two names actually driving the tape.
EQUITY_MEGACAP: Tuple[str, ...] = (
    "NVDA",
    "AAPL",
    "MU",
    "MSFT",
    "AMZN",
    "AMD",
    "GOOGL",
    "AVGO",
    "TSLA",
    "META",
)

# Roughly 30% of the index, and it moves together — a pricing or tariff headline
# lands on the whole complex, not on the one ticker it names. `same_bloc` exists
# so a chip event retains weight when the question is about a different chip
# name.
SEMI_COMPLEX: Tuple[str, ...] = (
    "NVDA",
    "MU",
    "AMD",
    "AVGO",
    "INTC",
    "AMAT",
    "LRCX",
    "KLAC",
    "TXN",
    "ASML",
    "MRVL",
)

# Written the way `asset_registry.GLOBAL_INDICES` writes them, so an index
# symbol means the same thing on both sides of the app.
INDEX_PROXIES: Tuple[str, ...] = ("^IXIC", "^GSPC")

# The crypto/equity transmission channel. MSTR is a Nasdaq-100 constituent as of
# 2026, so the bridge now sits inside the index itself rather than beside it.
BRIDGES: Tuple[str, ...] = ("MSTR", "COIN")

EQUITY_BELLWETHERS: Tuple[str, ...] = tuple(
    dict.fromkeys(EQUITY_MEGACAP + SEMI_COMPLEX + INDEX_PROXIES + BRIDGES)
)


# ═══════════════════════════════════════════════════════════════════════════════
# LOOKUPS
# ═══════════════════════════════════════════════════════════════════════════════

_CRYPTO_SET: FrozenSet[str] = frozenset(CRYPTO_BELLWETHERS)
_EQUITY_SET: FrozenSet[str] = frozenset(EQUITY_BELLWETHERS)
_SEMI_SET: FrozenSet[str] = frozenset(SEMI_COMPLEX)
_ALL_SET: FrozenSet[str] = _CRYPTO_SET | _EQUITY_SET


def normalize_symbol(symbol: Optional[str]) -> str:
    """
    A bare ticker, uppercased.

    Symbols reach this module from several places that spell them differently:
    the news pipeline carries exchange-qualified pairs ("BINANCE:BTCUSDT"), the
    registry carries bare tickers, and index symbols keep their caret. Matching
    on the raw string would silently miss most of them.
    """
    if not symbol:
        return ""

    text = symbol.strip().upper()
    if not text:
        return ""

    # "BINANCE:BTCUSDT" / "OKX:ETH-USDT" -> the part that names the asset.
    if ":" in text:
        text = text.split(":", 1)[1]

    # "ETH-USDT" / "ETH/USDT" -> "ETH". Index symbols carry no separator.
    for separator in ("-", "/"):
        if separator in text:
            text = text.split(separator, 1)[0]
            break

    # "BTCUSDT" -> "BTC". Only stripped when a known quote suffix leaves
    # something behind, so "USDT" itself and short tickers survive intact.
    for quote in ("USDT", "USDC", "BUSD", "USD"):
        if text.endswith(quote) and len(text) > len(quote):
            return text[: -len(quote)]

    return text


def is_bellwether(symbol: Optional[str]) -> bool:
    """Whether this asset's history is one the system deliberately learns from."""
    return normalize_symbol(symbol) in _ALL_SET


def bellwether_asset_type(symbol: Optional[str]) -> Optional[str]:
    """
    "crypto" or "stock" for a bellwether, None for anything else.

    Uses the same two labels the rest of the app uses (`asset_type` on news
    items and analysis requests), so the value can be compared directly.
    """
    ticker = normalize_symbol(symbol)
    if ticker in _CRYPTO_SET:
        return "crypto"
    if ticker in _EQUITY_SET:
        return "stock"
    return None


def same_bloc(symbol_a: Optional[str], symbol_b: Optional[str]) -> bool:
    """
    Whether two assets move as one group.

    Only the semiconductor complex qualifies today. Crypto majors are not a
    bloc in this sense — they follow BTC rather than each other, and that
    relationship is already covered by the bellwether spillover weight.
    """
    a, b = normalize_symbol(symbol_a), normalize_symbol(symbol_b)
    if not a or not b or a == b:
        return False
    return a in _SEMI_SET and b in _SEMI_SET


def default_crypto_symbols() -> List[str]:
    """
    Crypto symbols to index and to sweep by default.

    Several services each carried their own hardcoded list of "the important
    coins", which drifted apart. They now read this.
    """
    return list(CRYPTO_BELLWETHERS)


def default_equity_symbols() -> List[str]:
    """Equity symbols whose event history is worth measuring, indices excluded."""
    return [s for s in EQUITY_BELLWETHERS if not s.startswith("^")]
