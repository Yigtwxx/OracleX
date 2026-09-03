"""
The Radar's scoring rules, pinned where "no answer" and "zero" differ.

Every case here is a place the scan could quietly invent a reading: a missing
statement scored as a bad one, a veto softened into a low score, a consensus of
one analyst moving a total, a nominal revenue gain counted as growth in a year
inflation ate it.
"""

from services.bist.radar import scoring
from services.bist.radar.fundamentals import Fundamentals, Quarter
from services.bist.radar.profiles import PROFILES
from services.bist.radar.technical import Levels
from services.bist.tradingview_client import EquityRow


def _row(ticker: str = "TEST", **kwargs) -> EquityRow:
    defaults = {
        "ticker": ticker,
        "symbol": f"BIST:{ticker}",
        "name": "Test Sanayi A.Ş.",
        "price": 100.0,
        "change_pct": 0.01,
        "change_abs": 1.0,
        "volume": 1e6,
        "traded_value": 1e8,
        "market_cap": 1e10,
        "pe": 8.0,
        "pb": 1.2,
        "ev_ebitda": 5.0,
        "free_float_pct": 0.4,
        "sector": "Sanayi",
        "indices": ("XU100",),
        "sma50": 95.0,
        "sma200": 85.0,
        "rsi": 45.0,
    }
    defaults.update(kwargs)
    return EquityRow(**defaults)


def _quarter(period: str, **kwargs) -> Quarter:
    year, q = int(period[:4]), int(period[-1])
    defaults = {
        "revenue": 1000.0,
        "operating_profit": 100.0,
        "ebitda": 150.0,
        "net_income": 80.0,
        "financing_expense": -40.0,
        "ocf": 90.0,
        "fcf": 30.0,
        "dividends_paid": -10.0,
        "equity": 2000.0,
        "total_assets": 5000.0,
        "total_debt": 300.0,
        "short_term_debt": 100.0,
        "cash": 200.0,
        "current_assets": 1500.0,
        "current_liabilities": 900.0,
    }
    defaults.update(kwargs)
    return Quarter(period=period, year=year, quarter=q, **defaults)


PERIODS = ["2026Q2", "2026Q1", "2025Q4", "2025Q3", "2025Q2", "2025Q1", "2024Q4", "2024Q3"]


def _fund(layout: str = "industrial", **overrides) -> Fundamentals:
    quarters = tuple(_quarter(p, **overrides.get(p, {})) for p in PERIODS)
    return Fundamentals(
        ticker="TEST",
        layout=layout,
        quarters=quarters,
        fetched_at="2026-09-01T00:00:00+00:00",
        source_url="x",
    )


def _levels(**kwargs) -> Levels:
    defaults = {
        "entry_low": 94.0,
        "entry_high": 97.0,
        "stop": 91.0,
        "target1": 108.0,
        "target2": 115.0,
        "rr": 2.7,
        "atr": 3.0,
        "price": 96.0,
        "pullback_pct": 0.07,
        "rsi": 45.0,
        "rsi_divergence": None,
        "volume_ratio": 0.7,
        "structure": "higher",
        "zone_touches": 3,
        "zone_source": "support_zone",
        "range_position": 0.7,
        "ema_fast": 98.0,
        "ema_slow": 95.5,
        "high20": 103.0,
        "sma50_gap": 0.1,
    }
    defaults.update(kwargs)
    return Levels(**defaults)


SWING = PROFILES["swing"]


class TestWeighted:
    def test_missing_components_renormalise_rather_than_count_as_zero(self):
        assert scoring.weighted([(1.0, 50), (None, 50)]) == 1.0
        assert scoring.weighted([(None, 50), (None, 50)]) is None

    def test_scale_runs_both_directions(self):
        assert scoring.scale(0.0, 0.0, 4.0) == 0.0
        assert scoring.scale(0.0, 4.0, 0.0) == 1.0
        assert scoring.scale(None, 0.0, 1.0) is None


class TestSectorClass:
    def test_holding_named_company_is_a_holding_even_when_filed_as_a_bank(self):
        # TradingView puts Sabancı Holding under "Bölgesel bankalar".
        row = _row(name="HACI ÖMER SABANCI HOLDİNG", industry="Bölgesel bankalar")
        assert scoring.sector_class(row) == "holding"

    def test_industry_label_outranks_the_statement_layout(self):
        row = _row(name="AKSİGORTA", industry="Çok-kollu sigorta")
        assert scoring.sector_class(row, _fund(layout="bank")) == "insurance"

    def test_layout_decides_when_nothing_else_says(self):
        assert scoring.sector_class(_row(), _fund(layout="bank")) == "bank"
        assert scoring.sector_class(_row()) == "industrial"


class TestVetoes:
    def test_a_clean_company_has_no_vetoes(self):
        assert scoring.vetoes(_row(), _fund(), None) == []

    def test_three_losing_quarters_is_a_veto_not_a_low_score(self):
        fund = _fund(**{p: {"net_income": -5.0} for p in PERIODS[:3]})
        assert "losses_3_of_4" in scoring.vetoes(_row(), fund, None)

    def test_two_losing_quarters_is_not(self):
        fund = _fund(**{p: {"net_income": -5.0} for p in PERIODS[:2]})
        assert "losses_3_of_4" not in scoring.vetoes(_row(), fund, None)

    def test_net_debt_over_four_times_ebitda_is_a_veto_for_industrials_only(self):
        heavy = {p: {"total_debt": 4000.0, "cash": 0.0} for p in PERIODS}
        assert "net_debt_ebitda_gt_4" in scoring.vetoes(_row(), _fund(**heavy), None)
        bank = _row(name="TEST BANKASI", industry="Bölgesel bankalar")
        assert "net_debt_ebitda_gt_4" not in scoring.vetoes(
            bank, _fund(layout="bank", **heavy), None
        )

    def test_debt_against_negative_ebitda_is_the_worst_ratio_not_a_missing_one(self):
        fund = _fund(**{p: {"ebitda": -10.0} for p in PERIODS})
        assert scoring.net_debt_to_ebitda(fund) == float("inf")
        assert "net_debt_ebitda_gt_4" in scoring.vetoes(_row(), fund, None)

    def test_missing_statements_never_veto(self):
        assert scoring.vetoes(_row(), None, None) == []

    def test_kap_flags_are_vetoes(self):
        flags = scoring.KapFlags(rights_issue=True, restriction=True)
        assert scoring.vetoes(_row(), None, flags) == ["rights_issue_recent", "trading_restriction"]


class TestTechnicalScore:
    def test_a_textbook_pullback_scores_high(self):
        assert scoring.technical_score(_levels(), SWING) >= 80

    def test_reward_at_the_floor_scores_the_floor_not_zero(self):
        # A 1.5 that passed the gate is a tradeable setup, not a worthless one.
        low = scoring.technical_score(_levels(rr=1.5), SWING)
        high = scoring.technical_score(_levels(rr=3.5), SWING)
        assert 0 < low < high

    def test_heavy_selling_volume_costs_points(self):
        quiet = scoring.technical_score(_levels(volume_ratio=0.6), SWING)
        heavy = scoring.technical_score(_levels(volume_ratio=2.0), SWING)
        assert quiet > heavy

    def test_unknown_volume_is_left_out_rather_than_scored_as_heavy(self):
        unknown = scoring.technical_score(_levels(volume_ratio=None), SWING)
        heavy = scoring.technical_score(_levels(volume_ratio=2.0), SWING)
        assert unknown > heavy


class TestFundamentalScore:
    def test_full_statements_give_full_coverage(self):
        medians = scoring.sector_medians(
            [_row("A", pe=10), _row("B", pe=12), _row("C", pe=14), _row("D", pe=16)]
        )
        score, coverage = scoring.fundamental_score(_row(roe=0.35), _fund(), medians, 0.30)
        assert score is not None and 0 <= score <= 100
        assert coverage == 1.0

    def test_ratios_only_lowers_coverage_not_the_score_to_zero(self):
        medians = scoring.sector_medians(
            [_row("A", pe=10), _row("B", pe=12), _row("C", pe=14), _row("D", pe=16)]
        )
        score, coverage = scoring.fundamental_score(_row(roe=0.35), None, medians, 0.30)
        assert score is not None
        assert coverage < 1.0

    def test_growth_below_inflation_is_real_shrinkage(self):
        # Revenue up 20% nominal against 40% inflation.
        grew = _fund(**{p: {"revenue": 1200.0} for p in PERIODS[:4]})
        assert scoring.real_growth(grew, "revenue", 0.40) < 0
        assert scoring.real_growth(grew, "revenue", 0.10) > 0

    def test_growth_without_an_inflation_read_is_not_available(self):
        assert scoring.real_growth(_fund(), "revenue", None) is None

    def test_sector_median_needs_a_sample(self):
        medians = scoring.sector_medians([_row("A", pe=10), _row("B", pe=12)])
        assert medians["Sanayi"]["pe"] is None


class TestAnalystAdjuster:
    def test_fewer_than_three_analysts_move_nothing(self):
        row = _row(target_avg=150.0, analyst_count=2)
        assert scoring.analyst_adjustment(row) is None

    def test_a_wide_gap_adds_and_a_price_above_target_subtracts(self):
        assert scoring.analyst_adjustment(_row(target_avg=130.0, analyst_count=5)).points == 5
        assert scoring.analyst_adjustment(_row(target_avg=90.0, analyst_count=5)).points == -5
        assert scoring.analyst_adjustment(_row(target_avg=110.0, analyst_count=5)) is None


class TestTotal:
    def test_total_is_the_horizon_weighted_mix(self):
        assert scoring.total_score(80, 40, [], SWING) == 64
        assert scoring.total_score(80, 40, [], PROFILES["short"]) == 72

    def test_no_fundamental_score_means_the_technical_read_stands_alone(self):
        assert scoring.total_score(80, None, [], SWING) == 80

    def test_no_technical_read_means_no_total(self):
        assert scoring.total_score(None, 90, [], SWING) is None

    def test_adjusters_apply_after_the_mix_and_clamp(self):
        bump = scoring.Adjustment("x", "x", 5)
        assert scoring.total_score(80, 40, [bump], SWING) == 69
        assert scoring.total_score(100, 100, [bump], SWING) == 100
