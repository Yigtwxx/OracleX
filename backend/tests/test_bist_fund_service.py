"""
The TEFAS fund board.

Three seams carry the weight here:

* **Screening.** Which fund outranks which is the screener's entire answer, and
  the ordering rule for a fund with no figure for the sorted period is the part
  that is easy to get quietly wrong.
* **The risk-free estimate.** Sharpe against the wrong rate is worse than no
  Sharpe, and this board derives its rate from the funds themselves rather than
  from a keyed API — so the derivation needs pinning.
* **Failure.** An empty board reads to a user as "nothing matched your filter",
  which is a different and far more misleading statement than "TEFAS is down".

Nothing here touches the network: `fetch_fund_rows` and `fetch_fund_prices` are
monkeypatched at the module the service imports them into.
"""

import pytest

from services.bist import fund_service
from services.bist.fund_service import (
    FundDataUnavailable,
    distinct_umbrellas,
    estimate_risk_free_rate,
    fetch_fund_board,
    fetch_fund_detail,
    screen_funds,
)
from services.bist.tefas_client import FundPrices, FundRow, PricePoint, TefasUnavailable
from services.cache import bist_cache

from datetime import date


@pytest.fixture(autouse=True)
def _clean_cache():
    # The board is cached for half an hour and the cache is a module singleton,
    # so without this a test that primes it changes the answer for every test
    # that runs after it.
    bist_cache.clear()
    yield
    bist_cache.clear()


def _fund(
    code, *, umbrella="Hisse Senedi Şemsiye Fonu", tradable=True, risk=6, **returns
) -> FundRow:
    full = dict.fromkeys(("1a", "3a", "6a", "1y", "3y", "5y", "yb"))
    full.update(returns)
    return FundRow(
        code=code,
        title=f"{code} PORTFÖY FONU",
        umbrella=umbrella,
        tradable=tradable,
        risk_value=risk,
        returns=full,
    )


MONEY_MARKET = "Para Piyasası Şemsiye Fonu"


class TestScreening:
    def test_ranks_by_the_requested_period_descending(self):
        funds = [
            _fund("AAA", **{"1y": 0.2}),
            _fund("BBB", **{"1y": 0.9}),
            _fund("CCC", **{"1y": 0.5}),
        ]
        assert [f.code for f in screen_funds(funds, sort_by="1y")] == ["BBB", "CCC", "AAA"]

    def test_funds_without_a_figure_sort_last_not_as_zero(self):
        # A fund launched two months ago has no one-year return. Treating that
        # as 0% would file it among the funds that genuinely returned nothing,
        # which invents a result for it.
        funds = [_fund("NEW"), _fund("FLAT", **{"1y": 0.0}), _fund("DOWN", **{"1y": -0.3})]
        assert [f.code for f in screen_funds(funds, sort_by="1y")] == ["FLAT", "DOWN", "NEW"]

    def test_filters_untradable_funds_by_default(self):
        funds = [_fund("OPEN"), _fund("SHUT", tradable=False)]
        assert [f.code for f in screen_funds(funds)] == ["OPEN"]
        assert {f.code for f in screen_funds(funds, tradable_only=False)} == {"OPEN", "SHUT"}

    def test_filters_by_umbrella_exactly(self):
        funds = [_fund("EQ"), _fund("MM", umbrella=MONEY_MARKET)]
        assert [f.code for f in screen_funds(funds, umbrella=MONEY_MARKET)] == ["MM"]

    def test_risk_filter_keeps_funds_with_no_published_grade(self):
        # TEFAS leaves the grade blank for roughly one fund in nine. Dropping
        # those would silently shrink the board whenever the filter was touched.
        funds = [_fund("LOW", risk=2), _fund("HIGH", risk=7), _fund("UNGRADED", risk=None)]
        assert {f.code for f in screen_funds(funds, max_risk=3)} == {"LOW", "UNGRADED"}

    def test_search_matches_code_and_title_case_insensitively(self):
        funds = [_fund("PHE"), _fund("TLY")]
        assert [f.code for f in screen_funds(funds, search="phe")] == ["PHE"]
        assert [f.code for f in screen_funds(funds, search="portföy")] == ["PHE", "TLY"]

    def test_rejects_an_unknown_sort_period(self):
        with pytest.raises(ValueError):
            screen_funds([_fund("AAA")], sort_by="10y")

    def test_limit_applies_after_ranking(self):
        funds = [_fund("A", **{"1y": 0.1}), _fund("B", **{"1y": 0.9}), _fund("C", **{"1y": 0.5})]
        assert [f.code for f in screen_funds(funds, sort_by="1y", limit=2)] == ["B", "C"]


class TestRiskFreeEstimate:
    def test_uses_the_median_of_money_market_funds(self):
        funds = [
            _fund(f"M{i}", umbrella=MONEY_MARKET, **{"1y": rate})
            for i, rate in enumerate([0.43, 0.45, 0.47, 0.49, 0.60])
        ]
        funds.append(_fund("EQUITY", **{"1y": 2.2}))
        assert estimate_risk_free_rate(funds) == pytest.approx(0.47)

    def test_the_median_resists_a_single_outlier(self):
        # The published range runs to roughly 60%, and the top of it is funds
        # holding paper a money-market fund arguably should not. One of those
        # must not move the denominator of every ratio on the board.
        rates = [0.44, 0.45, 0.46, 0.47, 0.48]
        base = [_fund(f"M{i}", umbrella=MONEY_MARKET, **{"1y": r}) for i, r in enumerate(rates)]
        with_outlier = base + [_fund("WILD", umbrella=MONEY_MARKET, **{"1y": 4.0})]
        assert estimate_risk_free_rate(base) == pytest.approx(0.46)
        assert estimate_risk_free_rate(with_outlier) == pytest.approx(0.465)

    def test_none_when_too_few_funds_report(self):
        # The pension and ETF books, not a failure — but a rate derived from
        # two funds is not a rate, so no Sharpe is better than a bad one.
        funds = [_fund(f"M{i}", umbrella=MONEY_MARKET, **{"1y": 0.45}) for i in range(3)]
        assert estimate_risk_free_rate(funds) is None

    def test_ignores_money_market_funds_with_no_one_year_figure(self):
        funds = [_fund(f"M{i}", umbrella=MONEY_MARKET, **{"1y": 0.45}) for i in range(5)]
        funds += [_fund(f"N{i}", umbrella=MONEY_MARKET) for i in range(20)]
        assert estimate_risk_free_rate(funds) == pytest.approx(0.45)


class TestBoard:
    @pytest.mark.asyncio
    async def test_serves_the_board_and_the_derived_rate(self, monkeypatch):
        funds = [_fund(f"M{i}", umbrella=MONEY_MARKET, **{"1y": 0.45}) for i in range(5)]
        funds.append(_fund("PHE", **{"1y": 2.2}))

        async def fake_rows(fund_type="YAT"):
            return funds

        monkeypatch.setattr(fund_service, "fetch_fund_rows", fake_rows)
        board = await fetch_fund_board("YAT")
        assert len(board.funds) == 6
        assert board.risk_free_rate == pytest.approx(0.45)
        assert board.stale is False

    @pytest.mark.asyncio
    async def test_falls_back_to_the_last_snapshot_when_tefas_is_down(self, monkeypatch):
        funds = [_fund("PHE", **{"1y": 2.2})]
        calls = {"n": 0}

        async def flaky(fund_type="YAT"):
            calls["n"] += 1
            if calls["n"] == 1:
                return funds
            raise TefasUnavailable("boom")

        monkeypatch.setattr(fund_service, "fetch_fund_rows", flaky)
        first = await fetch_fund_board("YAT")
        assert first.stale is False

        # Expire the live entry but leave the fallback, which is what happens
        # thirty minutes later with TEFAS still down.
        bist_cache.invalidate("board:YAT")
        second = await fetch_fund_board("YAT")
        assert second.stale is True
        assert [f.code for f in second.funds] == ["PHE"]

    @pytest.mark.asyncio
    async def test_raises_rather_than_returning_an_empty_board(self, monkeypatch):
        # An empty screener renders as "no funds matched your filters", which is
        # a claim about the filters rather than about the upstream.
        async def none_at_all(fund_type="YAT"):
            return []

        monkeypatch.setattr(fund_service, "fetch_fund_rows", none_at_all)
        with pytest.raises(FundDataUnavailable):
            await fetch_fund_board("YAT")

    @pytest.mark.asyncio
    async def test_rejects_an_unknown_fund_type(self):
        with pytest.raises(ValueError):
            await fetch_fund_board("NOPE")


class TestDetail:
    @pytest.mark.asyncio
    async def test_computes_metrics_from_the_price_series(self, monkeypatch):
        async def fake_rows(fund_type="YAT"):
            return [_fund(f"M{i}", umbrella=MONEY_MARKET, **{"1y": 0.45}) for i in range(5)] + [
                _fund("PHE", **{"1y": 2.2})
            ]

        async def fake_prices(code, months=12):
            points = [
                PricePoint(day=date(2026, 1, 1 + i), price=100 * (1.01 if i % 2 else 0.995) ** i)
                for i in range(30)
            ]
            return FundPrices(
                code=code, title="PUSULA", category_rank=1, category_size=199, points=points
            )

        monkeypatch.setattr(fund_service, "fetch_fund_rows", fake_rows)
        monkeypatch.setattr(fund_service, "fetch_fund_prices", fake_prices)

        detail = await fetch_fund_detail("PHE", 12)
        assert detail.code == "PHE"
        assert detail.risk_free_rate == pytest.approx(0.45)
        assert detail.metrics.observations == 30
        assert len(detail.series) == 30
        # The board's own row travels with the detail, so the page can show the
        # umbrella and the published returns without a second request.
        assert detail.umbrella == "Hisse Senedi Şemsiye Fonu"
        assert detail.published_returns["1y"] == pytest.approx(2.2)

    @pytest.mark.asyncio
    async def test_a_fund_with_no_history_is_an_error_not_an_empty_chart(self, monkeypatch):
        async def fake_rows(fund_type="YAT"):
            return [_fund("PHE")]

        async def empty(code, months=12):
            return FundPrices(
                code=code, title="", category_rank=None, category_size=None, points=[]
            )

        monkeypatch.setattr(fund_service, "fetch_fund_rows", fake_rows)
        monkeypatch.setattr(fund_service, "fetch_fund_prices", empty)
        with pytest.raises(FundDataUnavailable):
            await fetch_fund_detail("PHE")

    @pytest.mark.asyncio
    async def test_survives_a_board_outage(self, monkeypatch):
        # The chart and every derived statistic work without the board; only
        # the umbrella, the grade and the risk-free rate are lost.
        async def board_down(fund_type="YAT"):
            raise TefasUnavailable("board down")

        async def fake_prices(code, months=12):
            points = [PricePoint(day=date(2026, 1, 1 + i), price=100 + i) for i in range(20)]
            return FundPrices(
                code=code, title="X", category_rank=None, category_size=None, points=points
            )

        monkeypatch.setattr(fund_service, "fetch_fund_rows", board_down)
        monkeypatch.setattr(fund_service, "fetch_fund_prices", fake_prices)

        detail = await fetch_fund_detail("PHE")
        assert detail.risk_free_rate is None
        assert detail.metrics.total_return is not None


def test_distinct_umbrellas_is_sorted_and_deduplicated():
    funds = [_fund("A"), _fund("B", umbrella=MONEY_MARKET), _fund("C"), _fund("D", umbrella="")]
    assert distinct_umbrellas(funds) == ["Hisse Senedi Şemsiye Fonu", MONEY_MARKET]


def test_search_survives_turkish_capitals():
    # `str.casefold` leaves a combining dot on `İ`, so an all-caps fund title —
    # which is how TEFAS publishes every one of them — stopped matching a
    # lowercase query containing the commonest letter in the language.
    funds = [_fund("IPB"), _fund("TPZ")]
    funds[0] = FundRow(
        code="IPB",
        title="İŞ PORTFÖY BİRİNCİ HİSSE SENEDİ FONU",
        umbrella="Hisse Senedi Şemsiye Fonu",
        tradable=True,
        risk_value=6,
        returns=dict.fromkeys(("1a", "3a", "6a", "1y", "3y", "5y", "yb")),
    )
    assert [f.code for f in screen_funds(funds, search="iş portföy")] == ["IPB"]
    assert [f.code for f in screen_funds(funds, search="İŞ PORTFÖY")] == ["IPB"]
