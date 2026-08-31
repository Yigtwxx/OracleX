"""The BIST fear-and-greed index, and what it refuses to answer."""

from services.bist.equity_service import SectorStat, sector_performance
from services.bist.sentiment_service import (
    MIN_MEASURED,
    band_label,
    breadth_component,
    compute_dominance,
    compute_sentiment,
    flow_component,
    limit_component,
    momentum_component,
    range_component,
)
from services.bist.tradingview_client import EquityRow


def row(
    ticker: str = "AAA",
    *,
    change_pct: float | None = 0.01,
    rsi: float | None = 50.0,
    price: float | None = 100.0,
    low: float | None = 50.0,
    high: float | None = 150.0,
    relative_volume: float | None = 1.0,
    market_cap: float | None = 1_000.0,
    traded_value: float | None = 1_000.0,
    sector: str = "Finans",
) -> EquityRow:
    return EquityRow(
        ticker=ticker,
        symbol=f"BIST:{ticker}",
        name=ticker,
        price=price,
        change_pct=change_pct,
        change_abs=None,
        volume=None,
        traded_value=traded_value,
        market_cap=market_cap,
        pe=None,
        pb=None,
        ev_ebitda=None,
        free_float_pct=None,
        sector=sector,
        week52_high=high,
        week52_low=low,
        rsi=rsi,
        relative_volume=relative_volume,
    )


def board(n: int, **kwargs) -> list[EquityRow]:
    return [row(f"A{i}", **kwargs) for i in range(n)]


# ── Components ───────────────────────────────────────────────────────────────


def test_breadth_scores_the_share_of_the_board_that_is_up():
    rows = board(3, change_pct=0.01) + board(1, change_pct=-0.01)
    component = breadth_component(rows)
    assert component is not None
    assert component.score == 75.0


def test_breadth_ignores_unchanged_rather_than_counting_them_as_fear():
    # An unchanged share is not a decline; folding it into the denominator would
    # drag every quiet session toward fear.
    rows = board(2, change_pct=0.01) + board(2, change_pct=0.0)
    component = breadth_component(rows)
    assert component is not None
    assert component.score == 100.0


def test_breadth_is_unavailable_when_nothing_moved():
    assert breadth_component(board(5, change_pct=0.0)) is None


def test_momentum_maps_the_conventional_rsi_band_onto_the_index():
    assert momentum_component(board(30, rsi=30.0)).score == 0.0
    assert momentum_component(board(30, rsi=50.0)).score == 50.0
    assert momentum_component(board(30, rsi=70.0)).score == 100.0
    # Beyond the band the indicator is already at its extreme; so is this.
    assert momentum_component(board(30, rsi=95.0)).score == 100.0


def test_momentum_uses_the_median_so_a_few_pinned_names_cannot_carry_it():
    rows = board(29, rsi=40.0) + [row("HOT", rsi=99.0)]
    component = momentum_component(rows)
    assert component is not None
    assert component.score == momentum_component(board(30, rsi=40.0)).score


def test_momentum_refuses_a_board_too_thin_to_describe():
    assert momentum_component(board(MIN_MEASURED - 1)) is None


def test_range_scores_position_between_the_yearly_bounds():
    assert range_component(board(30, price=50.0)).score == 0.0
    assert range_component(board(30, price=150.0)).score == 100.0
    assert range_component(board(30, price=100.0)).score == 50.0


def test_range_drops_a_price_outside_its_own_band_rather_than_clamping_it():
    # An unadjusted bonus issue leaves the quote below its own 52-week low;
    # clamping it would add a fake extreme to the median.
    rows = board(30, price=100.0) + board(30, price=10.0)
    component = range_component(rows)
    assert component is not None
    assert component.score == 50.0


def test_limit_reads_a_session_pinned_to_the_floor_as_maximum_fear():
    rows = board(10, change_pct=-0.10)
    assert limit_component(rows).score == 0.0


def test_limit_reads_a_session_pinned_to_the_ceiling_as_maximum_greed():
    assert limit_component(board(10, change_pct=0.10)).score == 100.0


def test_no_limit_move_is_neutral_rather_than_unmeasured():
    # A quiet session genuinely has no capitulation and no euphoria in it.
    component = limit_component(board(10, change_pct=0.01))
    assert component.score == 50.0
    assert component.reading == "limit hareketi yok"


def test_flow_leans_to_whichever_side_the_volume_is_on():
    rows = board(10, change_pct=0.01, relative_volume=2.0) + board(
        10, change_pct=-0.01, relative_volume=0.5
    )
    component = flow_component(rows)
    assert component is not None
    assert component.score > 65


def test_flow_needs_both_sides_before_it_can_compare_them():
    assert flow_component(board(30, change_pct=0.01)) is None


# ── The index ────────────────────────────────────────────────────────────────


def test_a_board_at_its_lows_and_limit_down_reads_as_extreme_fear():
    rows = board(40, change_pct=-0.10, rsi=20.0, price=52.0, relative_volume=2.0)
    sentiment = compute_sentiment(rows)
    assert sentiment is not None
    assert sentiment.score <= 24
    assert sentiment.label == "Aşırı korku"


def test_a_board_at_its_highs_and_limit_up_reads_as_extreme_greed():
    rows = board(40, change_pct=0.10, rsi=80.0, price=148.0, relative_volume=2.0)
    sentiment = compute_sentiment(rows)
    assert sentiment is not None
    assert sentiment.score >= 76
    assert sentiment.label == "Aşırı açgözlülük"


def test_the_index_refuses_a_board_too_thin_to_measure():
    assert compute_sentiment(board(MIN_MEASURED - 1)) is None


def test_the_index_refuses_when_too_few_components_survive():
    # Nothing moved and nothing has an RSI, a price band or a volume ratio:
    # only the limit component can answer, and one component is not an index.
    rows = [
        row(f"A{i}", change_pct=0.0, rsi=None, price=None, relative_volume=None) for i in range(40)
    ]
    assert compute_sentiment(rows) is None


def test_every_component_is_explained_in_the_units_it_was_measured_in():
    sentiment = compute_sentiment(board(40, change_pct=0.01, relative_volume=1.0))
    assert sentiment is not None
    assert all(c.reading for c in sentiment.components)
    assert all(0.0 <= c.score <= 100.0 for c in sentiment.components)


def test_bands_cover_the_whole_range_without_a_gap():
    assert band_label(0) == "Aşırı korku"
    assert band_label(24) == "Aşırı korku"
    assert band_label(25) == "Korku"
    assert band_label(50) == "Nötr"
    assert band_label(56) == "Açgözlülük"
    assert band_label(100) == "Aşırı açgözlülük"


# ── Dominance ────────────────────────────────────────────────────────────────


def test_dominance_names_the_largest_sector_and_its_share():
    rows = [
        row("BANK1", sector="Finans", market_cap=700.0),
        row("BANK2", sector="Finans", market_cap=200.0),
        row("TECH1", sector="Elektronik teknoloji", market_cap=100.0),
    ]
    dominance = compute_dominance(rows, sector_performance(rows))
    assert dominance.sector == "Finans"
    assert dominance.sector_weight == 0.9


def test_dominance_measures_how_much_of_the_session_is_one_name():
    rows = [
        row("BIG", traded_value=800.0),
        row("B", traded_value=100.0),
        row("C", traded_value=100.0),
    ]
    dominance = compute_dominance(rows, [])
    assert dominance.top_ticker == "BIG"
    assert dominance.top_turnover_share == 0.8
    assert dominance.top5_turnover_share == 1.0


def test_dominance_answers_nulls_rather_than_zeros_on_an_empty_board():
    dominance = compute_dominance([], [])
    assert dominance.sector is None
    assert dominance.top_ticker is None
    assert dominance.top_turnover_share is None


def test_dominance_survives_a_sector_list_it_was_not_given():
    rows = [row("A", traded_value=10.0)]
    dominance = compute_dominance(rows, [])
    assert dominance.sector is None
    assert dominance.top_ticker == "A"


def test_sector_stat_shape_is_what_dominance_reads():
    # Guards the coupling: dominance reads three fields off SectorStat and a
    # rename upstream would silently null them.
    stat = SectorStat(
        sector="Finans",
        count=1,
        market_cap=1.0,
        weight=1.0,
        change_pct=0.01,
        advancers=1,
        decliners=0,
    )
    dominance = compute_dominance([row("A")], [stat])
    assert dominance.sector == "Finans"
    assert dominance.sector_weight == 1.0
    assert dominance.sector_change_pct == 0.01


def test_readings_use_the_turkish_decimal_comma():
    # Every other figure on this realm does; a lone `1.4x` beside `%31,8` reads
    # as a different product's number.
    rows = board(10, change_pct=0.01, relative_volume=2.0) + board(
        10, change_pct=-0.01, relative_volume=0.5
    )
    component = flow_component(rows)
    assert component is not None
    assert "." not in component.reading
    assert "2,0×" in component.reading

    positions = range_component(board(30, price=100.0))
    assert positions is not None
    assert "," in positions.reading
