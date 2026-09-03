"""
The read above the BIST macro page.

Everything the model is allowed to say is computed here, so this file tests the
computation and never the prose. What carries the weight:

* **Fisher, not subtraction.** The real rate is the one figure on the page a
  reader works out wrong in their head, and a regression to subtraction would
  be a plausible number rather than an obvious one.
* **The lira's change is anchored on dates, not on row counts.** A series with
  a holiday in it has fewer points than days, and counting back thirty rows
  would measure six weeks and call it a month.
* **Degraded upstreams are stated.** The consumer index and the tape are each
  allowed to be absent; the facts must say so rather than fill in.
* **`macro_values` derives from the facts and from nothing else.**
"""

from datetime import UTC, datetime

import pytest

from services.bist import macro_note as n
from services.bist.kap_service import Disclosure, KapUnavailable
from services.bist.macro_service import MacroSnapshot, MacroUnavailable


def snapshot(**overrides) -> MacroSnapshot:
    fields = {
        "inflation_yoy": 0.32,
        "ppi_yoy": 0.28,
        "policy_rate": 0.37,
        "cpi_index": 3000.0,
        "unemployment": 0.081,
        "gdp_yoy": 0.023,
        "usdtry": 48.31,
        "eurtry": 55.96,
        "as_of": "2026-09-02T07:34:13.324354+00:00",
        "stale": False,
    }
    fields.update(overrides)
    return MacroSnapshot(**fields)


def fx_series(days: int = 400, start: float = 40.0, end: float = 48.0) -> list[dict]:
    """A daily series ending on 2026-09-01, rising linearly, no weekends removed."""
    from datetime import date, timedelta

    last = date(2026, 9, 1)
    return [
        {
            "date": (last - timedelta(days=days - 1 - index)).isoformat(),
            "rate": start + (end - start) * index / (days - 1),
        }
        for index in range(days)
    ]


def disclosure(
    title: str,
    *,
    ticker: str = "THYAO",
    published_at: str | None = "2026-09-01T10:00:00+03:00",
    index: int = 1,
) -> Disclosure:
    return Disclosure(
        index=index,
        title=title,
        company="Borsa İstanbul",
        ticker=ticker,
        category="ODA",
        category_label="Özel Durum Açıklaması",
        published_at=published_at,
        summary="",
        is_late=False,
        url="https://www.kap.org.tr/",
    )


# ── Classification ───────────────────────────────────────────────────────────


def test_the_real_rate_is_fisher_rather_than_subtraction():
    # 37% against 32%: subtraction says 5 points, Fisher says under 4.
    real = n.real_policy_rate(0.37, 0.32)
    assert real == pytest.approx(0.0379, abs=0.0001)
    assert n.real_policy_rate(None, 0.32) is None
    assert n.real_policy_rate(0.37, None) is None


@pytest.mark.parametrize(
    ("real_pct", "expected"),
    [
        (None, n.STANCE_REAL_NEAR_ZERO),
        (4.0, n.STANCE_REAL_POSITIVE),
        (2.0, n.STANCE_REAL_POSITIVE),
        (1.5, n.STANCE_REAL_NEAR_ZERO),
        (-1.5, n.STANCE_REAL_NEAR_ZERO),
        (-2.0, n.STANCE_REAL_NEGATIVE),
        (-8.0, n.STANCE_REAL_NEGATIVE),
    ],
)
def test_the_stance_has_a_two_point_deadband(real_pct, expected):
    assert n.classify_macro_stance(real_pct) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("THYAO.E Devre Kesici Uygulaması", "circuit_breaker"),
        ("Açığa Satış Yasağı Hakkında", "short_selling"),
        ("Brüt Takas Uygulaması", "gross_settlement"),
        ("Kredili İşlem Yasağı", "margin_trading"),
        ("İşlem Sırası Kapatma", "session_closure"),
        ("Fiyat Limiti Değişikliği", "price_limit"),
        ("VBTS Kapsamında Tedbir", "other"),
    ],
)
def test_measures_are_classed_by_the_exchanges_fixed_phrasing(title, expected):
    assert n.measure_kind(disclosure(title)) == expected


# ── The lira ─────────────────────────────────────────────────────────────────


def test_the_change_is_anchored_on_calendar_days():
    series = fx_series()
    # 400 points across 400 days at a constant slope: a year back is 365 days
    # of slope, whatever the row count.
    change = n.fx_change(series, 365)
    expected = series[-1]["rate"] / series[-366]["rate"] - 1
    assert change == pytest.approx(expected)


def test_a_series_that_does_not_reach_back_far_enough_measures_nothing():
    assert n.fx_change(fx_series(days=20), 30) is None
    assert n.fx_change([], 30) is None
    assert n.fx_change([{"date": "2026-09-01", "rate": 48.0}], 30) is None


def test_a_gap_in_the_series_anchors_on_the_last_point_before_the_target():
    series = [
        {"date": "2026-07-25", "rate": 40.0},
        {"date": "2026-08-05", "rate": 44.0},  # skipped: after the target
        {"date": "2026-09-01", "rate": 48.0},
    ]
    assert n.fx_change(series, 30) == pytest.approx(0.2)


# ── The pace of prices ───────────────────────────────────────────────────────


def test_momentum_needs_four_months_and_reads_the_last_three():
    series = [{"month": f"2026-{i}", "index": 1000.0 * 1.03**i} for i in range(1, 6)]
    pace = n.cpi_momentum(series)
    assert pace["month"] == "2026-5"
    assert pace["mom_pct"] == 3.0
    assert pace["three_month_annualized_pct"] == 42.5
    assert n.cpi_momentum(series[:3]) is None
    assert n.cpi_momentum([]) is None


# ── The exchange's measures ─────────────────────────────────────────────────


def test_measures_are_counted_inside_the_window_only():
    now = datetime(2026, 9, 2, tzinfo=UTC)
    rows = [
        disclosure("Devre Kesici", index=1),
        disclosure("Devre Kesici", ticker="SASA", index=2),
        disclosure("Açığa Satış Yasağı", ticker="ASELS", index=3),
        disclosure("Devre Kesici", ticker="OLD", published_at="2026-08-01T10:00:00+03:00", index=4),
        disclosure("Devre Kesici", ticker="NOSTAMP", published_at=None, index=5),
    ]
    measures = n.measures_in_window(rows, now)
    assert measures["total"] == 3
    assert measures["by_kind"] == {"circuit_breaker": 2, "short_selling": 1}
    assert measures["tickers"] == ["THYAO", "SASA", "ASELS"]
    assert measures["latest_day"] == "2026-09-01"


def test_a_calm_week_is_a_count_of_zero_rather_than_an_absence():
    measures = n.measures_in_window([], datetime(2026, 9, 2, tzinfo=UTC))
    assert measures["total"] == 0
    assert "No exchange measure" in n.macro_values(sample_facts(measures=measures))["measures"]


# ── Aggregation off a snapshot ───────────────────────────────────────────────


def test_the_facts_carry_the_crossings_the_tiles_cannot():
    facts = n.facts_from_snapshot(snapshot(), fx_series(), [], None)
    assert facts is not None
    assert facts["stance"] == n.STANCE_REAL_POSITIVE
    assert facts["as_of"] == "2026-09-02"
    assert facts["rates"]["policy_pct"] == 37.0
    assert facts["rates"]["inflation_pct"] == 32.0
    assert facts["rates"]["real_policy_pct"] == 4.0
    assert facts["rates"]["ppi_cpi_gap_pct"] == -4.0
    assert facts["fx"]["usdtry"] == 48.3
    assert facts["fx"]["change_12m_pct"] is not None
    assert facts["fx"]["carry_12m_pct"] == n._bucket(37.0 - facts["fx"]["change_12m_pct"], 0.5)
    assert facts["prices"] is None
    assert facts["measures"] is None


def test_without_the_two_anchor_figures_there_is_nothing_to_read():
    assert n.facts_from_snapshot(snapshot(policy_rate=None), [], [], None) is None
    assert n.facts_from_snapshot(snapshot(inflation_yoy=None), [], [], None) is None


def test_a_small_move_does_not_retire_the_note():
    """The snapshot refreshes every half hour and the lira inside it moves on
    every refresh; a fingerprint that moved with it would run a local model
    all day."""
    before = n.facts_from_snapshot(snapshot(usdtry=48.31), [], [], None)
    after = n.facts_from_snapshot(snapshot(usdtry=48.33, inflation_yoy=0.3202), [], [], None)
    assert before == after


@pytest.fixture
def upstream(monkeypatch):
    state = {
        "snapshot": snapshot(),
        "fx": fx_series(),
        "cpi": [],
        "tape": [disclosure("Devre Kesici")],
        "snapshot_error": None,
        "tape_error": None,
    }

    async def macro():
        if state["snapshot_error"]:
            raise state["snapshot_error"]
        return state["snapshot"]

    async def fx(range_="1y"):
        return state["fx"]

    async def cpi(years=6):
        return state["cpi"]

    async def tape(limit, *, ticker=None, categories=None):
        if state["tape_error"]:
            raise state["tape_error"]
        return state["tape"]

    monkeypatch.setattr(n, "fetch_macro_snapshot", macro)
    monkeypatch.setattr(n, "fetch_usdtry_series", fx)
    monkeypatch.setattr(n, "fetch_cpi_series", cpi)
    monkeypatch.setattr(n, "fetch_tape", tape)
    return state


@pytest.mark.asyncio
async def test_the_builder_reads_all_four_upstreams(upstream):
    facts = await n.build_macro_facts()
    assert facts["measures"]["total"] >= 0
    assert facts["fx"]["series_points"] == 400


@pytest.mark.asyncio
async def test_a_snapshot_outage_produces_no_facts(upstream):
    upstream["snapshot_error"] = MacroUnavailable("scanner down")
    assert await n.build_macro_facts() is None


@pytest.mark.asyncio
async def test_a_tape_outage_costs_the_measures_and_nothing_else(upstream):
    upstream["tape_error"] = KapUnavailable("blocked")
    facts = await n.build_macro_facts()
    assert facts is not None
    assert facts["measures"] is None
    assert "could not be read" in n.macro_values(facts)["measures"]


@pytest.mark.asyncio
async def test_the_note_refuses_rather_than_narrating_nothing():
    note = await n.macro_note(None)
    assert note["status"] == "unavailable"
    assert note["reason"] == "insufficient_data"


# ── Prompt rendering ─────────────────────────────────────────────────────────


def sample_facts(**overrides) -> dict:
    facts = {
        "stance": n.STANCE_REAL_POSITIVE,
        "as_of": "2026-09-02",
        "stale": False,
        "rates": {
            "policy_pct": 37.0,
            "inflation_pct": 31.8,
            "ppi_pct": 27.8,
            "real_policy_pct": 4.0,
            "ppi_cpi_gap_pct": -4.0,
            "unemployment_pct": 8.1,
            "gdp_pct": 2.3,
        },
        "fx": {
            "usdtry": 48.3,
            "eurtry": 56.0,
            "change_1m_pct": 1.5,
            "change_3m_pct": 5.0,
            "change_12m_pct": 17.5,
            "carry_12m_pct": 19.5,
            "series_points": 260,
        },
        "prices": {"month": "2026-1", "mom_pct": 4.8, "three_month_annualized_pct": 29.5},
        "measures": {
            "window_days": 7,
            "total": 3,
            "by_kind": {"circuit_breaker": 2, "short_selling": 1},
            "tickers": ["THYAO", "SASA"],
            "latest_day": "2026-09-01",
        },
        "not_measured": list(n.NOT_MEASURED),
    }
    facts.update(overrides)
    return facts


def test_values_fill_every_placeholder_the_prompt_declares():
    from services.prompts import load_prompt

    template = load_prompt("notes/bist_macro")
    values = n.macro_values(sample_facts())
    for key in values:
        assert f"{{{{{key}}}}}" in template, f"{key} is rendered but never used"
    for key in ("stance", "rates", "fx", "prices", "measures", "staleness", "not_measured"):
        assert key in values


def test_the_real_rate_is_labelled_as_fisher_in_the_prompt():
    rates = n.macro_values(sample_facts())["rates"]
    assert "NOT by subtraction" in rates
    assert "+4.0%" in rates


def test_an_absent_index_is_stated_rather_than_filled_in():
    prices = n.macro_values(sample_facts(prices=None))["prices"]
    assert "not available" in prices
    assert "unmeasured" in prices


def test_measures_are_listed_by_kind_and_by_name():
    measures = n.macro_values(sample_facts())["measures"]
    assert "circuit breaker: 2" in measures
    assert "short-selling ban: 1" in measures
    assert "THYAO, SASA" in measures


def test_staleness_is_a_sentence_either_way():
    assert "current" in n.macro_values(sample_facts())["staleness"]
    assert "cache" in n.macro_values(sample_facts(stale=True))["staleness"]


# ── The route ────────────────────────────────────────────────────────────────


def test_the_macro_note_endpoint_answers_facts_and_prose(monkeypatch):
    from fastapi.testclient import TestClient

    from main import app

    async def facts():
        return {"stance": "real_positive"}

    async def note(given):
        assert given == {"stance": "real_positive"}
        return {"status": "ready", "note": "Reel faiz", "generated_at": None, "reason": None}

    monkeypatch.setattr("routers.bist.build_macro_facts", facts)
    monkeypatch.setattr("routers.bist.macro_note", note)

    payload = TestClient(app).get("/api/bist/macro-note").json()
    assert payload["facts"] == {"stance": "real_positive"}
    assert payload["note"]["status"] == "ready"


def test_an_unreadable_backdrop_answers_null_facts(monkeypatch):
    from fastapi.testclient import TestClient

    from main import app

    async def facts():
        return None

    monkeypatch.setattr("routers.bist.build_macro_facts", facts)

    payload = TestClient(app).get("/api/bist/macro-note").json()
    assert payload["facts"] is None
    assert payload["note"]["reason"] == "insufficient_data"
