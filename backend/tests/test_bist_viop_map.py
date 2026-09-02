"""
The VİOP margin scan band model.

Three things are pinned here, and each is a place where a wrong answer would
look entirely reasonable on screen.

**The direction rule.** It is the one inferred input on the board, and it has to
match `quadrantOf` in `frontend/lib/bist-positioning.ts` exactly — including
returning nothing on the axis, where a flat settlement is the absence of the
signal rather than a weak version of it.

**The band arithmetic.** `entry × (1 ± PSR)` with the scan range read from the
snapshot, so that the day Takasbank revises a rate the assertion fails loudly
instead of the board shifting quietly.

**The basis conversion.** Three expiries trade at three prices for one company;
drawn without adjustment, one wall of positioning becomes three.
"""

import pytest

from services.bist.takasbank_psr import PsrSnapshot, UnderlyingPsr
from services.bist.viop_bulletin import SsfRow
from services.bist.viop_margin_map import (
    MIN_OPEN_INTEREST_CONTRACTS,
    SIDE_LONG,
    SIDE_SHORT,
    build_margin_map,
    direction,
)


def _price_of(board, cell) -> float:
    return board.price_min + (cell.bin_index + 0.5) * board.bin_size


def _column(board, column: int = 0):
    return [cell for cell in board.cells if cell.column == column]


def _band(board, column: int = 0) -> tuple[float, float]:
    """The lowest and highest price the deposited band covers."""
    prices = [_price_of(board, cell) for cell in _column(board, column)]
    assert prices, "expected a populated column"
    return min(prices), max(prices)


def _deposited(board, column: int = 0) -> float:
    """Everything standing in one column, both sides."""
    return sum(cell.long_try + cell.short_try for cell in _column(board, column))


from services.cache import bist_cache


@pytest.fixture(autouse=True)
def _clean_cache():
    bist_cache.clear()
    yield
    bist_cache.clear()


def _psr(**rates: float) -> PsrSnapshot:
    return PsrSnapshot(
        rates={
            code: UnderlyingPsr(underlying=code, psr=value, contract_value=None, multiplier=100)
            for code, value in rates.items()
        },
        as_of="20260828",
        run="1",
        created="202608282128",
        source_file="TAKASEOD_-CCP__-BI-_____-260828-001.zip",
        stored_at=0.0,
    )


def _row(day: str, **kwargs) -> SsfRow:
    defaults = {
        "day": day,
        "contract": "F_THYAO0826",
        "underlying": "THYAO",
        "expiry": "2026-08-31",
        "settlement": 100.0,
        "previous_settlement": 99.0,
        "high": 101.0,
        "low": 99.0,
        "weighted_average": 100.0,
        "volume_try": 1_000_000.0,
        "contracts_traded": 100.0,
        "open_interest": 50_000.0,
        "open_interest_change": 1_000.0,
        "multiplier": 100,
    }
    defaults.update(kwargs)
    return SsfRow(**defaults)


class TestDirectionRule:
    def test_rising_open_interest_on_an_up_day_is_a_long(self):
        assert direction(100, 101.0, 100.0) == SIDE_LONG

    def test_rising_open_interest_on_a_down_day_is_a_short(self):
        assert direction(100, 99.0, 100.0) == SIDE_SHORT

    def test_a_flat_settlement_assigns_nothing(self):
        # The axis, not a faint reading on either side of it. `quadrantOf`
        # returns null here for the same reason.
        assert direction(100, 100.0, 100.0) is None

    def test_falling_open_interest_assigns_nothing(self):
        # A position closing is not a position opening. There is no volume term
        # here inventing exposure the exchange did not report.
        assert direction(-100, 101.0, 100.0) is None
        assert direction(0, 101.0, 100.0) is None

    def test_a_missing_previous_settlement_assigns_nothing(self):
        assert direction(100, 101.0, None) is None


class TestBandArithmetic:
    def test_a_long_band_sits_a_scan_range_below_entry(self):
        board = build_margin_map(
            [_row("2026-08-26", settlement=101.0, previous_settlement=100.0)],
            _psr(THYAO=0.134),
            {"2026-08-26": 101.0},
            underlying="THYAO",
        )
        assert board is not None
        cells = _column(board)
        assert all(cell.long_try > 0 and cell.short_try == 0 for cell in cells)
        # Three rungs below the entry, at a third, two thirds and all of the
        # scan range — a ladder, not one line. The shallowest is what puts heat
        # near price rather than only at the far end.
        low, high = _band(board)
        assert low == pytest.approx(100.0 * (1 - 0.134), rel=0.03)
        assert high == pytest.approx(100.0 * (1 - 0.134 / 3), rel=0.03)

    def test_all_three_rungs_are_placed(self):
        board = build_margin_map(
            [_row("2026-08-26", settlement=101.0, previous_settlement=100.0)],
            _psr(THYAO=0.134),
            {"2026-08-26": 101.0},
            underlying="THYAO",
        )
        # One mark per rung, not a smear across them: spreading each deposit
        # over the session's traded range merged neighbouring levels into slabs
        # and cost the field its texture.
        assert len(_column(board)) == 3

    def test_the_full_scan_range_carries_the_most_weight(self):
        board = build_margin_map(
            [_row("2026-08-26", settlement=101.0, previous_settlement=100.0)],
            _psr(THYAO=0.134),
            {"2026-08-26": 101.0},
            underlying="THYAO",
        )
        # The rung where the margin is actually exhausted must not be drawn
        # fainter than the intermediate stress points above it.
        heaviest = max(_column(board), key=lambda cell: cell.long_try)
        assert _price_of(board, heaviest) == pytest.approx(100.0 * (1 - 0.134), rel=0.03)

    def test_a_short_band_sits_a_scan_range_above_entry(self):
        board = build_margin_map(
            [_row("2026-08-26", settlement=99.0, previous_settlement=100.0)],
            _psr(THYAO=0.134),
            {"2026-08-26": 99.0},
            underlying="THYAO",
        )
        cells = _column(board)
        assert all(cell.short_try > 0 and cell.long_try == 0 for cell in cells)
        low, high = _band(board)
        assert low == pytest.approx(100.0 * (1 + 0.134 / 3), rel=0.03)
        assert high == pytest.approx(100.0 * (1 + 0.134), rel=0.03)

    def test_the_scan_range_is_read_per_underlying(self):
        # THYAO 13.4% and AKBNK 15.7% are different bands on the same price.
        # A single shared constant would put them in the same place.
        thyao = build_margin_map(
            [_row("2026-08-26", settlement=101.0, previous_settlement=100.0)],
            _psr(THYAO=0.134, AKBNK=0.157),
            {"2026-08-26": 101.0},
            underlying="THYAO",
        )
        akbnk = build_margin_map(
            [
                _row(
                    "2026-08-26",
                    underlying="AKBNK",
                    settlement=101.0,
                    previous_settlement=100.0,
                )
            ],
            _psr(THYAO=0.134, AKBNK=0.157),
            {"2026-08-26": 101.0},
            underlying="AKBNK",
        )
        assert thyao.psr == 0.134
        assert akbnk.psr == 0.157

    def test_an_underlying_without_a_published_rate_gets_no_map(self):
        # The distance is a published number. There is no version of this that
        # substitutes one, so the answer is nothing rather than a guess.
        assert (
            build_margin_map(
                [_row("2026-08-26")], _psr(AKBNK=0.157), {"2026-08-26": 100.0}, underlying="THYAO"
            )
            is None
        )


class TestNotionalAndCohorts:
    def test_notional_is_the_published_change_times_size_and_price(self):
        board = build_margin_map(
            [
                _row(
                    "2026-08-26",
                    settlement=101.0,
                    previous_settlement=100.0,
                    open_interest_change=1_000.0,
                    weighted_average=100.0,
                    multiplier=100,
                )
            ],
            _psr(THYAO=0.134),
            {"2026-08-26": 101.0},
            underlying="THYAO",
        )
        # Spread across the band, so the invariant is conservation rather than
        # the value of any one cell: a wider session must not deposit more.
        assert _deposited(board) == pytest.approx(1_000 * 100 * 100.0)

    def test_a_flat_session_is_counted_not_placed(self):
        board = build_margin_map(
            [_row("2026-08-26", settlement=100.0, previous_settlement=100.0)],
            _psr(THYAO=0.134),
            {"2026-08-26": 100.0},
            underlying="THYAO",
        )
        assert board.cells == []
        assert board.undirected_sessions == 1
        assert board.undirected_notional == pytest.approx(1_000 * 100 * 100.0)

    def test_a_closing_session_places_nothing_and_counts_nothing(self):
        board = build_margin_map(
            [_row("2026-08-26", open_interest_change=-5_000.0)],
            _psr(THYAO=0.134),
            {"2026-08-26": 100.0},
            underlying="THYAO",
        )
        assert board.cells == []
        assert board.undirected_sessions == 0


class TestSweep:
    def test_a_level_the_contract_trades_through_is_spent(self):
        # Day one opens a long, so its band sits near 86.6 and that column
        # carries a cell. Day two's range covers that price, which spends the
        # level — so the streak stops and the later columns hold nothing.
        rows = [
            _row("2026-08-26", settlement=101.0, previous_settlement=100.0),
            _row(
                "2026-08-27",
                settlement=86.0,
                previous_settlement=101.0,
                high=101.0,
                low=80.0,
                weighted_average=86.0,
                open_interest_change=0.0,
            ),
            _row(
                "2026-08-28",
                settlement=86.0,
                previous_settlement=86.0,
                high=87.0,
                low=85.0,
                weighted_average=86.0,
                open_interest_change=0.0,
            ),
        ]
        board = build_margin_map(
            rows,
            _psr(THYAO=0.134),
            {"2026-08-26": 101.0, "2026-08-27": 86.0, "2026-08-28": 86.0},
            underlying="THYAO",
        )
        columns = {cell.column for cell in board.cells}
        assert columns == {0}, "the level should survive only the session that opened it"

    def test_a_surviving_level_repeats_in_every_column(self):
        # The repetition is the whole reason the map reads as a field: an
        # untouched level paints its row again on each session it lives through.
        rows = [
            _row("2026-08-26", settlement=101.0, previous_settlement=100.0),
            _row(
                "2026-08-27",
                settlement=101.5,
                previous_settlement=101.0,
                high=102.0,
                low=101.0,
                weighted_average=101.5,
                open_interest_change=0.0,
            ),
        ]
        board = build_margin_map(
            rows,
            _psr(THYAO=0.134),
            {"2026-08-26": 101.0, "2026-08-27": 101.5},
            underlying="THYAO",
        )
        assert {cell.column for cell in board.cells} == {0, 1}
        # Same bins in both columns: the level did not move, it survived.
        assert {cell.bin_index for cell in _column(board, 0)} == {
            cell.bin_index for cell in _column(board, 1)
        }


class TestBasis:
    def test_a_premium_expiry_lands_on_its_spot_price(self):
        # A contract settling at 106 against a spot of 100 carries a 6% basis.
        # The band belongs at 100 × (1 − psr), not at 106 × (1 − psr).
        board = build_margin_map(
            [
                _row(
                    "2026-08-26",
                    settlement=106.0,
                    previous_settlement=105.0,
                    weighted_average=106.0,
                    high=106.5,
                    low=105.5,
                )
            ],
            _psr(THYAO=0.134),
            {"2026-08-26": 100.0},
            underlying="THYAO",
        )
        # A contract settling at 106 against a spot of 100 carries a 6% basis,
        # so the ladder belongs under 100, not under 106.
        low, high = _band(board)
        assert low == pytest.approx(100.0 * (1 - 0.134), rel=0.03)
        assert high == pytest.approx(100.0 * (1 - 0.134 / 3), rel=0.03)

    def test_expiries_share_one_grid(self):
        rows = [
            _row("2026-08-26", contract="F_THYAO0826", expiry="2026-08-31", settlement=100.5),
            _row("2026-08-26", contract="F_THYAO0926", expiry="2026-09-30", settlement=104.0),
            _row("2026-08-26", contract="F_THYAO1026", expiry="2026-10-30", settlement=108.0),
        ]
        board = build_margin_map(rows, _psr(THYAO=0.134), {"2026-08-26": 100.0}, underlying="THYAO")
        assert board.expiries == ["2026-08-31", "2026-09-30", "2026-10-30"]
        # All three converted onto one axis, so the grid is not three prices wide.
        assert board.price_max / board.price_min < 2.0

    def test_a_missing_spot_close_carries_the_basis_forward(self):
        rows = [_row("2026-08-26"), _row("2026-08-27"), _row("2026-08-28")]
        board = build_margin_map(
            rows,
            _psr(THYAO=0.134),
            {"2026-08-26": 100.0, "2026-08-28": 100.0},
            underlying="THYAO",
        )
        assert board.basis_carried_sessions == 1
        assert board.dropped_sessions == 0
        assert len(board.sessions) == 3

    def test_no_spot_history_at_all_yields_no_map(self):
        assert (
            build_margin_map([_row("2026-08-26")], _psr(THYAO=0.134), {}, underlying="THYAO")
            is None
        )


class TestFieldShape:
    def test_the_strongest_cell_is_reported_for_the_ramp(self):
        board = build_margin_map(
            [_row("2026-08-26", settlement=101.0, previous_settlement=100.0)],
            _psr(THYAO=0.134),
            {"2026-08-26": 101.0},
            underlying="THYAO",
        )
        # The strongest single cell, which is a share of the spread cohort
        # rather than the whole of it.
        assert 0 < board.max_value <= 1_000 * 100 * 100.0


class TestThinUnderlyings:
    def test_a_thin_book_is_flagged(self):
        board = build_margin_map(
            [_row("2026-08-26", open_interest=MIN_OPEN_INTEREST_CONTRACTS - 1)],
            _psr(THYAO=0.134),
            {"2026-08-26": 100.0},
            underlying="THYAO",
        )
        assert board.thin is True

    def test_a_deep_book_is_not(self):
        board = build_margin_map(
            [_row("2026-08-26", open_interest=MIN_OPEN_INTEREST_CONTRACTS * 10)],
            _psr(THYAO=0.134),
            {"2026-08-26": 100.0},
            underlying="THYAO",
        )
        assert board.thin is False


class TestGrid:
    def test_the_grid_reaches_past_the_traded_range_by_a_full_band(self):
        # A band landing outside the grid is dropped, and dropping the deepest
        # ones on whichever side price sits closer to would read as an absence
        # of positioning rather than as clipping.
        rows = [_row("2026-08-26", high=105.0, low=95.0, settlement=101.0)]
        board = build_margin_map(rows, _psr(THYAO=0.134), {"2026-08-26": 101.0}, underlying="THYAO")
        assert board.price_min < 95.0 * (1 - 0.134) + 1
        assert board.price_max > 105.0 * (1 + 0.134) - 1

    def test_sessions_come_back_in_order(self):
        rows = [_row(day) for day in ("2026-08-28", "2026-08-26", "2026-08-27")]
        board = build_margin_map(
            rows,
            _psr(THYAO=0.134),
            {"2026-08-26": 100.0, "2026-08-27": 100.0, "2026-08-28": 100.0},
            underlying="THYAO",
        )
        assert board.sessions == ["2026-08-26", "2026-08-27", "2026-08-28"]


class TestRegressionAgainstTheFrontendRule:
    @pytest.mark.parametrize(
        "oi_change,settlement,previous,expected",
        [
            (100, 102.0, 100.0, SIDE_LONG),
            (100, 98.0, 100.0, SIDE_SHORT),
            (-100, 102.0, 100.0, None),
            (-100, 98.0, 100.0, None),
            (0, 102.0, 100.0, None),
            (100, 100.0, 100.0, None),
        ],
    )
    def test_matches_quadrant_of(self, oi_change, settlement, previous, expected):
        """
        The same six cases `bist-positioning.test.ts` asserts on `quadrantOf`.

        Only the two build quadrants place a cohort — a cover or a liquidation
        is open interest leaving, which this board does not draw — but the
        mapping from (open interest, price) to a side has to agree, or the
        terminal is asserting two different things about one dataset.
        """
        assert direction(oi_change, settlement, previous) == expected
