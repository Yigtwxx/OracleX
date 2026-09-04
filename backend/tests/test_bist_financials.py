"""
Statements into the Bilanço board's payload.

Two properties carry most of the weight here. The first is that `LAYOUT_FIELDS`
still describes what the parser produces — a map that has drifted from the item
codes beside it turns a bank's page into five empty panels with no error
anywhere. The second is direction: the deflator must make older quarters larger,
and the served quarters must run oldest-first while `Fundamentals` runs
newest-first. Both failures produce a well-formed, plausible, wrong chart.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from services.bist import deflator, fundamentals as f
from services.bist import financials_service as fs

FIXTURES = Path(__file__).parent / "fixtures"
PERIODS = [(2026, 6), (2026, 3), (2025, 12), (2025, 9)]


def _rows(name: str) -> list[dict]:
    return json.loads((FIXTURES / f"isyatirim_{name}_2026Q2.json").read_text())["value"]


def _fundamentals(name: str, group: str) -> f.Fundamentals:
    rows = _rows(name)
    layout = f.detect_layout(rows, group)
    quarters = f.build_quarters(f.parse_periods(rows, PERIODS), layout)
    return f.Fundamentals(
        ticker=name.upper(),
        layout=layout,
        quarters=quarters,
        fetched_at=datetime.now(UTC).isoformat(),
        source_url=f.STATEMENTS_URL,
    )


def industrial() -> f.Fundamentals:
    return _fundamentals("thyao", "XI_29")


def bank() -> f.Fundamentals:
    return _fundamentals("akbnk", "UFRS")


def insurer() -> f.Fundamentals:
    """No fixture exists for an insurer, so one is built from the layout's own fields."""
    quarters = tuple(
        f.Quarter(
            period=f"2026Q{q}" if q else "2025Q4",
            year=2026 if q else 2025,
            quarter=q or 4,
            net_income=1_000_000.0 * (q + 1),
            equity=50_000_000.0,
            total_assets=200_000_000.0,
        )
        for q in (2, 1, 0)
    )
    return f.Fundamentals(
        ticker="ANHYT",
        layout=f.LAYOUT_INSURANCE,
        quarters=quarters,
        fetched_at=datetime.now(UTC).isoformat(),
        source_url=f.STATEMENTS_URL,
    )


def _periods(count: int) -> list[tuple[str, int, int]]:
    """`count` quarter labels, newest first, ending at 2026Q2."""
    out, year, quarter = [], 2026, 2
    for _ in range(count):
        out.append((f"{year}Q{quarter}", year, quarter))
        quarter -= 1
        if quarter == 0:
            year, quarter = year - 1, 4
    return out


def long_series(layout: str, count: int = 12, *, growth: float = 1.05) -> f.Fundamentals:
    """
    A synthetic company long enough for trailing arithmetic.

    The fixtures carry four periods, which the parser differences into three
    quarters — enough to test parsing and deflation, and one short of anything
    trailing. Growth figures need eight quarters and a comparison needs twelve.
    """
    quarters = []
    for index, (period, year, quarter) in enumerate(_periods(count)):
        scale = growth ** (count - index)
        common = {
            "period": period,
            "year": year,
            "quarter": quarter,
            "net_income": 10.0 * scale,
            "equity": 500.0 * scale,
            "total_assets": 2_000.0 * scale,
        }
        if layout == f.LAYOUT_INSURANCE:
            quarters.append(f.Quarter(**common))
            continue
        common["revenue"] = 100.0 * scale
        common["operating_profit"] = 20.0 * scale
        if layout == f.LAYOUT_BANK:
            quarters.append(f.Quarter(**common))
            continue
        quarters.append(
            f.Quarter(
                **common,
                gross_profit=30.0 * scale,
                ebitda=25.0 * scale,
                financing_expense=-4.0 * scale,
                ocf=12.0 * scale,
                capex=-6.0 * scale,
                fcf=6.0 * scale,
                dividends_paid=-2.0 * scale,
                total_debt=300.0 * scale,
                short_term_debt=120.0 * scale,
                cash=80.0 * scale,
                current_assets=400.0 * scale,
                current_liabilities=350.0 * scale,
            )
        )
    return f.Fundamentals("SYNTH", layout, tuple(quarters), "", "")


def cpi(count: int = 60, *, start_year: int = 2022, step: float = 1.03) -> list[dict]:
    out, value = [], 100.0
    year, month = start_year, 1
    for _ in range(count):
        out.append({"month": f"{year}-{month:02d}", "index": round(value, 4)})
        value *= step
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return out


def payload(fund: f.Fundamentals, **kw):
    kw.setdefault("cpi_series", cpi())
    kw.setdefault("key_configured", True)
    return fs.build_payload(fund, **kw)


class TestLayoutCoverage:
    @pytest.mark.parametrize("builder", [industrial, bank, insurer])
    def test_layout_fields_still_describes_what_the_parser_produces(self, builder):
        # The highest-value test in this module. `LAYOUT_FIELDS` is a hand-kept
        # mirror of the item-code maps in `fundamentals.py`; when the two drift,
        # nothing raises and the board simply renders panels that will never
        # fill. Both directions are asserted: everything claimed is produced,
        # and nothing outside the claim ever appears.
        fund = builder()
        declared = set(fs.LAYOUT_FIELDS[fund.layout])

        produced = {
            field
            for field in fs.FIELD_KEYS
            if any(getattr(q, field, None) is not None for q in fund.quarters)
        }
        assert produced <= declared, f"parser produced fields {produced - declared} not declared"
        assert declared - produced == set(), (
            f"declared fields never produced by this layout: {declared - produced}"
        )

    @pytest.mark.parametrize("builder", [industrial, bank, insurer])
    def test_available_is_a_subset_of_the_layout(self, builder):
        data = payload(builder())
        assert set(data["available_fields"]) <= set(data["layout_fields"])

    def test_a_line_reported_in_any_quarter_counts_as_available(self):
        # Present-if-any, not present-if-newest: a company that stopped
        # reporting a line should show a chart with a gap, not lose the panel.
        fund = industrial()
        blanked = fund.quarters[0].__class__(**{**fund.quarters[0].__dict__, "gross_profit": None})
        patched = f.Fundamentals(
            ticker=fund.ticker,
            layout=fund.layout,
            quarters=(blanked,) + fund.quarters[1:],
            fetched_at=fund.fetched_at,
            source_url=fund.source_url,
        )
        assert "gross_profit" in payload(patched)["available_fields"]


class TestInsurer:
    def test_thin_layout_still_returns_a_board(self):
        # A thin company is not an error. The endpoint answers 200 and the page
        # renders the panels it can.
        data = payload(insurer())
        assert set(data["available_fields"]) == {"net_income", "equity", "total_assets"}
        assert data["ttm"]["real_revenue_growth"] is None
        assert len(data["quarters"]) == 3

    def test_every_revenue_derived_ratio_is_none(self):
        for row in payload(insurer())["ratios"]:
            assert row["gross_margin"] is None
            assert row["net_margin"] is None
            assert row["ebitda_margin"] is None


class TestBank:
    def test_gross_and_ebitda_margins_do_not_exist(self):
        data = payload(bank())
        for row in data["ratios"]:
            assert row["gross_margin"] is None
            assert row["ebitda_margin"] is None
            assert row["net_debt_ebitda"] is None

    def test_net_margin_is_computed(self):
        # Needs a trailing year, which the four-period fixture cannot supply.
        rows = payload(long_series(f.LAYOUT_BANK))["ratios"]
        assert any(row["net_margin"] is not None for row in rows)
        assert all(row["gross_margin"] is None for row in rows)


class TestOrdering:
    def test_served_quarters_run_oldest_first(self):
        # Fundamentals is newest-first because every trailing calculation counts
        # backwards. A chart reads left to right, and a silent reversal is a
        # plausible picture of the opposite trend.
        fund = industrial()
        data = payload(fund)
        assert fund.quarters[0].period == data["quarters"][-1]["period"]
        periods = [q["period"] for q in data["quarters"]]
        assert periods == sorted(periods)

    def test_ratios_run_oldest_first_too(self):
        periods = [r["period"] for r in payload(industrial())["ratios"]]
        assert periods == sorted(periods)


class TestPassThrough:
    def test_quarterly_flows_are_not_recomputed_here(self):
        # The year-to-date differencing belongs to `fundamentals` and is pinned
        # by its own tests. A second copy of that arithmetic in this module is
        # exactly how the two would drift.
        fund = industrial()
        data = payload(fund)
        by_period = {q["period"]: q["nominal"] for q in data["quarters"]}
        for quarter in fund.quarters:
            assert by_period[quarter.period]["revenue"] == quarter.revenue
            assert by_period[quarter.period]["net_income"] == quarter.net_income


class TestDeflation:
    def test_older_quarters_are_restated_upward_and_the_newest_is_the_base(self):
        data = payload(industrial())
        oldest, newest = data["quarters"][0], data["quarters"][-1]
        assert newest["deflator"] == pytest.approx(1.0)
        assert newest["real"]["revenue"] == pytest.approx(newest["nominal"]["revenue"])
        assert oldest["real"]["revenue"] > oldest["nominal"]["revenue"]

    def test_deflators_decrease_monotonically_with_recency(self):
        factors = [q["deflator"] for q in payload(industrial())["quarters"]]
        assert all(a > b for a, b in zip(factors, factors[1:]))

    def test_unavailable_leaves_nominal_untouched_and_real_absent(self):
        # The failure this pins: a real block silently reusing the nominal
        # figures would render nominal lira under a "Reel" label.
        live = payload(industrial())
        dead = payload(industrial(), cpi_series=[], key_configured=False)

        assert dead["deflation"]["available"] is False
        assert dead["deflation"]["reason"] == deflator.REASON_KEY_MISSING
        for served, reference in zip(dead["quarters"], live["quarters"]):
            assert served["real"] is None
            assert served["deflator"] is None
            assert served["nominal"] == reference["nominal"]

    def test_no_key_and_outage_are_told_apart(self):
        assert (
            payload(industrial(), cpi_series=[], key_configured=True)["deflation"]["reason"]
            == deflator.REASON_UNAVAILABLE
        )

    def test_quarters_older_than_the_series_carry_no_real_block(self):
        short = [{"month": "2026-06", "index": 300.0}, {"month": "2026-03", "index": 280.0}]
        data = payload(industrial(), cpi_series=short)
        assert data["deflation"]["available"] is True
        uncovered = set(data["deflation"]["uncovered_periods"])
        assert uncovered, "fixture should have quarters older than a two-month series"
        for quarter in data["quarters"]:
            if quarter["period"] in uncovered:
                assert quarter["real"] is None
                assert quarter["nominal"]["revenue"] is not None


class TestRatios:
    def test_roe_uses_average_equity_not_closing(self):
        # A company that doubled its equity mid-year reads materially lower on
        # the average formula. In Turkey the capital raise is the common case,
        # so the flattering version would be the one usually shown.
        quarters = []
        for index in range(8):
            equity = 100.0 if index >= 4 else 200.0
            quarters.append(
                f.Quarter(
                    period=f"P{index}",
                    year=2026,
                    quarter=1,
                    revenue=100.0,
                    net_income=10.0,
                    equity=equity,
                )
            )
        fund = f.Fundamentals("X", f.LAYOUT_INDUSTRIAL, tuple(quarters), "", "")
        latest = fs.build_ratios(fund)[-1]
        # TTM net income 40 over average(200, 100) = 150 → 0.2667, not 40/200.
        assert latest["roe_ttm"] == pytest.approx(40 / 150)
        assert latest["roe_ttm"] != pytest.approx(40 / 200)

    def test_net_debt_to_ebitda_is_never_infinite_on_the_wire(self):
        # `scoring.net_debt_to_ebitda` answers inf for debt against non-positive
        # EBITDA, which is right for a veto and not encodable as JSON.
        quarters = tuple(
            f.Quarter(
                period=f"P{i}",
                year=2026,
                quarter=1,
                revenue=100.0,
                ebitda=-5.0,
                net_income=-5.0,
                total_debt=500.0,
                cash=1.0,
                equity=50.0,
            )
            for i in range(8)
        )
        fund = f.Fundamentals("X", f.LAYOUT_INDUSTRIAL, quarters, "", "")
        for row in fs.build_ratios(fund):
            assert row["net_debt_ebitda"] is None
        json.dumps(fs.build_ratios(fund))  # must encode

    def test_whole_payload_is_json_encodable(self):
        json.dumps(payload(industrial()))
        json.dumps(payload(bank()))
        json.dumps(payload(insurer()))


class TestTtm:
    def test_nominal_and_real_growth_disagree_under_inflation(self):
        # The board's entire argument, as an assertion.
        data = payload(long_series(f.LAYOUT_INDUSTRIAL))
        ttm = data["ttm"]
        assert ttm["nominal_revenue_growth"] is not None
        assert ttm["real_revenue_growth"] is not None
        assert ttm["real_revenue_growth"] < ttm["nominal_revenue_growth"]

    def test_loss_quarters_is_none_rather_than_zero_on_a_short_window(self):
        # "No loss-making quarter" and "we cannot see four quarters" are
        # different statements and must not share a rendering.
        assert payload(insurer())["ttm"]["loss_quarters"] is None
