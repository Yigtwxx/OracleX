"""
News attribution must never invent an asset.

The dashboard charts whatever symbol a news item carries and hands the same
symbol to the analyser, so a wrong attribution is not a cosmetic slip — it puts
an unrelated price series on screen and tells the model the story is about an
asset it never mentions.

These pin down the behaviour that replaced the previous detector, which
- discarded the model's "no asset here" answer and let a substring matcher
  overrule it,
- matched coin names as substrings ("t*rain*ing" → RAIN) and bare tickers as
  words ("**US** inflation" → USUSDT, "is **not** moving" → NOTUSDT),
- returned any unparseable model output verbatim as a symbol, and
- labelled every unlisted coin BINANCE:, producing charts TradingView cannot
  draw.

Nothing here touches the network: the registry and the LLM are both faked.
"""

import asyncio

import pytest

from services import symbol_detection_service as sd
from services.ai_service import SymbolVerdict, parse_symbol_answer

# ── Fakes ───────────────────────────────────────────────────────────────────

FAKE_LISTED = {
    "BINANCE": ["BTC", "ETH", "SOL", "XRP", "PEPE", "POL"],
    # PI trades on OKX only — the case that used to chart as BINANCE:PIUSDT.
    "OKX": ["BTC", "ETH", "SOL", "PI"],
}

FAKE_EQUITIES = {
    "AAPL": {"name": "Apple Inc.", "exchange": "NASDAQ", "market_cap": 3.5e12},
    "TSLA": {"name": "Tesla Inc.", "exchange": "NASDAQ", "market_cap": 1.1e12},
    "COIN": {"name": "Coinbase Global Inc.", "exchange": "NASDAQ", "market_cap": 6e10},
    "JPM": {"name": "JP Morgan Chase & Co.", "exchange": "NYSE", "market_cap": 7e11},
    "TGT": {"name": "Target Corporation", "exchange": "NYSE", "market_cap": 6e10},
    "CACC": {"name": "Credit Acceptance Corporation", "exchange": "NASDAQ", "market_cap": 4e9},
    "APLE": {"name": "Apple Hospitality REIT Inc.", "exchange": "NYSE", "market_cap": 3e9},
}

FAKE_UNIVERSE = [
    {"id": "bitcoin", "symbol": "BTC", "name": "Bitcoin", "market_cap": 2e12},
    {"id": "ethereum", "symbol": "ETH", "name": "Ethereum", "market_cap": 4e11},
    {"id": "solana", "symbol": "SOL", "name": "Solana", "market_cap": 8e10},
    {"id": "ripple", "symbol": "XRP", "name": "XRP", "market_cap": 1e11},
    {"id": "pepe", "symbol": "PEPE", "name": "Pepe", "market_cap": 4e9},
    {"id": "pi-network", "symbol": "PI", "name": "Pi Network", "market_cap": 3e9},
    # The names that used to be matched as substrings.
    {"id": "rain", "symbol": "RAIN", "name": "Rain", "market_cap": 2e8},
    {"id": "notcoin", "symbol": "NOT", "name": "Notcoin", "market_cap": 3e8},
    {"id": "us-token", "symbol": "US", "name": "US", "market_cap": 1e8},
    {"id": "sleepless-ai", "symbol": "AI", "name": "Sleepless AI", "market_cap": 5e7},
    # A coin that no exchange in the fake listing carries.
    {"id": "unlisted", "symbol": "ZZZ", "name": "Zzz Protocol", "market_cap": 1e8},
]


@pytest.fixture(autouse=True)
def fake_registry(monkeypatch):
    """Point the detector at fixed listings instead of the live registry."""

    async def listed_bases():
        return FAKE_LISTED

    async def equity_index():
        return FAKE_EQUITIES

    async def equity_exchange(symbol):
        record = FAKE_EQUITIES.get(symbol.upper())
        return record["exchange"] if record else None

    async def crypto_universe(limit=250):
        return FAKE_UNIVERSE[:limit]

    async def exchange_for_crypto(base):
        for exchange in ("BINANCE", "OKX"):
            if base.upper() in FAKE_LISTED.get(exchange, ()):
                return exchange
        return None

    monkeypatch.setattr(sd.asset_registry, "get_listed_bases", listed_bases)
    monkeypatch.setattr(sd.asset_registry, "get_us_equity_index", equity_index)
    monkeypatch.setattr(sd.asset_registry, "equity_exchange", equity_exchange)
    monkeypatch.setattr(sd.asset_registry, "get_crypto_universe", crypto_universe)
    monkeypatch.setattr(sd.asset_registry, "exchange_for_crypto", exchange_for_crypto)
    # The name tables are memoised; a fresh cache per test keeps the fakes honest.
    sd._lookup_cache.invalidate("crypto_names")
    sd._lookup_cache.invalidate("equity_names")
    yield
    sd._lookup_cache.invalidate("crypto_names")
    sd._lookup_cache.invalidate("equity_names")


def fake_llm(monkeypatch, *, symbol=None, answered=True):
    """Make the model return one fixed verdict, recording the calls it got."""
    calls = []

    async def detect(text, asset_type="crypto"):
        calls.append((text, asset_type))
        return SymbolVerdict(symbol=symbol, answered=answered)

    monkeypatch.setattr(sd, "detect_asset_symbol", detect)
    return calls


def detect(text, title, asset_type="crypto"):
    return asyncio.run(sd.detect_symbol_smart(text, title, asset_type))


# ── The model's "no asset" answer is an answer ───────────────────────────────


class TestModelSaysNoAsset:
    def test_null_answer_is_final(self, monkeypatch):
        """
        The heuristic matcher must not get a second opinion.

        "The Fed is not moving rates" contains the word "not", and Notcoin's
        ticker is NOT. The old code reached that matcher on every null answer.
        """
        fake_llm(monkeypatch, symbol=None, answered=True)

        result = detect("", "The Fed is not moving rates this month")

        assert result.symbol is None
        assert result.confident is True

    def test_macro_headline_stays_unattributed(self, monkeypatch):
        fake_llm(monkeypatch, symbol=None, answered=True)

        assert detect("", "Markets remain flat ahead of the jobs print").symbol is None


# ── Unreachable model falls back, but only to spelled-out names ──────────────


class TestFallbackWhenModelUnreachable:
    @pytest.mark.parametrize(
        "title",
        [
            "US inflation cools in June",  # coin ticker US
            "AI training data lawsuit hits chipmakers",  # coin tickers AI, RAIN
            "The Fed is not moving rates this month",  # coin ticker NOT
            "Nasdaq closes lower as tech breadth narrows",
            "Credit Suisse pursuit of a merger",  # Credit Acceptance Corp
            "Analysts raise their price target for the sector",  # Target Corp
        ],
    )
    def test_ordinary_words_are_not_tickers(self, monkeypatch, title):
        fake_llm(monkeypatch, answered=False)

        assert detect("", title).symbol is None

    def test_spelled_out_coin_name_is_matched(self, monkeypatch):
        fake_llm(monkeypatch, answered=False)

        assert detect("", "Bitcoin surges past 100k on ETF inflows").symbol == "BINANCE:BTCUSDT"

    def test_spelled_out_company_name_is_matched(self, monkeypatch):
        fake_llm(monkeypatch, answered=False)

        result = detect("", "Tesla recalls 2000 vehicles over a software fault", "stock")
        assert result.symbol == "NASDAQ:TSLA"

    def test_larger_company_wins_a_shared_name(self, monkeypatch):
        """Apple Inc., not Apple Hospitality REIT."""
        fake_llm(monkeypatch, answered=False)

        assert detect("", "Apple unveils new features", "stock").symbol == "NASDAQ:AAPL"

    def test_fallback_results_are_marked_unconfident(self, monkeypatch):
        """So the attribution cache revisits them once a model is reachable."""
        fake_llm(monkeypatch, answered=False)

        assert detect("", "Bitcoin surges past 100k").confident is False


# ── Every candidate is confirmed against a live listing ──────────────────────


class TestResolutionGate:
    def test_unlisted_coin_is_rejected(self, monkeypatch):
        fake_llm(monkeypatch, symbol="BINANCE:ZZZUSDT")

        assert detect("", "Zzz Protocol announces a rebrand").symbol is None

    def test_unknown_ticker_is_rejected(self, monkeypatch):
        fake_llm(monkeypatch, symbol="NASDAQ:ZZZZ")

        assert detect("", "Some company reports earnings", "stock").symbol is None

    def test_exchange_comes_from_the_listing_not_the_model(self, monkeypatch):
        """PI is not on Binance; charting it there produces an invalid symbol."""
        fake_llm(monkeypatch, symbol="BINANCE:PIUSDT")

        assert detect("", "Pi Network opens mainnet").symbol == "OKX:PIUSDT"

    def test_equity_exchange_is_corrected(self, monkeypatch):
        fake_llm(monkeypatch, symbol="NASDAQ:JPM")

        assert detect("", "JP Morgan raises guidance", "stock").symbol == "NYSE:JPM"

    def test_migrated_ticker_is_normalised(self, monkeypatch):
        """MATIC no longer trades; Polygon is POL."""
        fake_llm(monkeypatch, symbol="MATIC")

        assert detect("", "Polygon ships an upgrade").symbol == "BINANCE:POLUSDT"


# ── Asset class follows the asset, not the feed ──────────────────────────────


class TestAssetClass:
    def test_stock_story_on_a_crypto_feed(self, monkeypatch):
        """CoinDesk covering Coinbase earnings is reporting on a stock."""
        fake_llm(monkeypatch, symbol="NASDAQ:COIN")

        result = detect("", "Coinbase beats earnings expectations", "crypto")

        assert result.symbol == "NASDAQ:COIN"
        assert result.asset_type == "stock"

    def test_crypto_story_on_a_stock_feed(self, monkeypatch):
        fake_llm(monkeypatch, symbol="BINANCE:BTCUSDT")

        result = detect("", "Bitcoin ETF inflows hit a record", "stock")

        assert result.symbol == "BINANCE:BTCUSDT"
        assert result.asset_type == "crypto"

    def test_unattributed_item_keeps_the_feed_class(self, monkeypatch):
        fake_llm(monkeypatch, symbol=None, answered=True)

        assert detect("", "Markets drift sideways", "stock").asset_type == "stock"


# ── Explicit market notation ─────────────────────────────────────────────────


class TestExplicitNotation:
    def test_cashtag_short_circuits_the_model(self, monkeypatch):
        calls = fake_llm(monkeypatch, symbol="BINANCE:ETHUSDT")

        assert detect("", "$BTC breaks out").symbol == "BINANCE:BTCUSDT"
        assert calls == []

    def test_cashtag_works_for_equities_too(self, monkeypatch):
        fake_llm(monkeypatch, answered=False)

        assert detect("", "$AAPL hits a record high", "stock").symbol == "NASDAQ:AAPL"

    def test_tagged_ticker_in_parentheses(self, monkeypatch):
        fake_llm(monkeypatch, answered=False)

        result = detect("", "Coinbase Global (NASDAQ: COIN) posts a profit", "stock")
        assert result.symbol == "NASDAQ:COIN"

    def test_defined_acronym_is_not_a_ticker(self, monkeypatch):
        """ "artificial intelligence (AI)" is a definition, not a stock tag."""
        fake_llm(monkeypatch, symbol=None, answered=True)

        assert detect("", "Artificial intelligence (AI) spending accelerates").symbol is None

    def test_unlisted_cashtag_does_not_win(self, monkeypatch):
        """A cashtag is explicit, but it still has to name something real."""
        fake_llm(monkeypatch, symbol=None, answered=True)

        assert detect("", "$FAKE is going to the moon").symbol is None


class TestAcronymsAreNotTickers:
    """
    Several real tickers are, in market copy, almost always acronyms. A model
    asked to name a symbol reaches for one anyway.
    """

    def test_acronym_answer_is_refused(self, monkeypatch):
        fake_llm(monkeypatch, symbol="BINANCE:AIUSDT")

        result = detect("", "MEXC expands its offerings with AI integration")
        assert result.symbol is None

    def test_cashtagged_acronym_is_accepted(self, monkeypatch):
        """When the author writes $AI, they mean the token."""
        monkeypatch.setitem(sd.CRYPTO_ALIASES, "ai", "AI")
        monkeypatch.setitem(FAKE_LISTED, "BINANCE", [*FAKE_LISTED["BINANCE"], "AI"])
        fake_llm(monkeypatch, symbol="BINANCE:AIUSDT")

        assert detect("", "$AI rallies after the airdrop").symbol == "BINANCE:AIUSDT"


class TestNamedAssetCorrectsANearMiss:
    """
    Models reach for a plausible neighbouring ticker. The exchange listing knows
    which company a name belongs to, and that outranks recall.
    """

    def test_the_named_company_wins(self, monkeypatch):
        """ "Tesla recalls vehicles" is TSLA, whatever ticker the model produced."""
        fake_llm(monkeypatch, symbol="NASDAQ:AAPL")

        result = detect("", "Tesla recalls 2000 vehicles", "stock")
        assert result.symbol == "NASDAQ:TSLA"

    def test_a_headline_naming_two_assets_keeps_the_model_choice(self, monkeypatch):
        """
        Only the model read the article, so when the headline names both it
        decides which one the story is about.
        """
        fake_llm(monkeypatch, symbol="NASDAQ:TSLA")

        result = detect("", "JP Morgan raises its rating on Tesla", "stock")
        assert result.symbol == "NASDAQ:TSLA"

    def test_an_unnamed_asset_is_left_alone(self, monkeypatch):
        """No name in the headline means no counter-evidence to act on."""
        fake_llm(monkeypatch, symbol="NASDAQ:COIN")

        result = detect("", "The exchange posts a surprise quarterly profit", "stock")
        assert result.symbol == "NASDAQ:COIN"


# ── Model output parsing ─────────────────────────────────────────────────────


class TestParseSymbolAnswer:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("BINANCE:BTCUSDT", "BINANCE:BTCUSDT"),
            ("  NASDAQ:AAPL  ", "NASDAQ:AAPL"),
            ('"NYSE:JPM"', "NYSE:JPM"),
            ("`BINANCE:ETHUSDT`", "BINANCE:ETHUSDT"),
            ("NASDAQ:TSLA.", "NASDAQ:TSLA"),
            ("BINANCE:SOLUSDT is the answer", "BINANCE:SOLUSDT"),
        ],
    )
    def test_symbols_survive_the_usual_wrapping(self, raw, expected):
        assert parse_symbol_answer(raw).symbol == expected

    @pytest.mark.parametrize("raw", ["null", "NULL", " null ", "none"])
    def test_null_is_an_answer(self, raw):
        verdict = parse_symbol_answer(raw)
        assert verdict.symbol is None
        assert verdict.answered is True

    @pytest.mark.parametrize("raw", ["", "   ", "\n"])
    def test_empty_completion_is_no_answer(self, raw):
        verdict = parse_symbol_answer(raw)
        assert verdict.symbol is None
        # Not "no asset" — nothing was said, so the caller should fall back.
        assert verdict.answered is False

    @pytest.mark.parametrize(
        "raw",
        [
            "the answer is unclear here",
            "$$$",
            "…",
        ],
    )
    def test_prose_never_becomes_a_symbol(self, raw):
        """
        The old parser returned anything it could not classify verbatim, so a
        completion of "Bitcoin" became the item's symbol and was charted as one.
        """
        assert parse_symbol_answer(raw).symbol is None


class TestUnvalidatedAnswersNeverEscape:
    """
    Whatever the parser lets through, only listed assets reach the caller.

    The parser cannot tell "AAPL" from "BITCOIN" by shape alone, and it should
    not try: the listing is the authority on what exists.
    """

    def test_a_name_the_alias_table_knows_is_resolved(self, monkeypatch):
        fake_llm(monkeypatch, symbol="BITCOIN")

        assert detect("", "A story about bitcoin").symbol == "BINANCE:BTCUSDT"

    def test_a_name_nothing_knows_is_dropped(self, monkeypatch):
        fake_llm(monkeypatch, symbol="SOMECOMPANY")

        assert detect("", "A story about somecompany", "stock").symbol is None
