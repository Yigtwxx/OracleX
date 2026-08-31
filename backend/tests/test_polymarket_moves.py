"""
Finding the windows a market re-priced in.

These windows are the search terms for "why was this bet opened" — each one
becomes a dated news query. So a false positive is not noise, it is a stage of
the pipeline spent explaining an afternoon in which nothing happened, and a
false negative loses the event that made the market worth opening.

The series below are hand-built rather than captured, because the properties
being tested are shape properties: flat, one step, two steps. A real capture
would test one market's history instead of the rule.
"""

from datetime import datetime, timedelta, UTC

from models.polymarket import PricePoint
from services.polymarket.moves import MIN_DELTA, detect_sharp_moves

START = datetime(2026, 3, 1, tzinfo=UTC)


def series(values: list[float], *, step_minutes: int = 60) -> list[PricePoint]:
    return [
        PricePoint(t=START + timedelta(minutes=step_minutes * i), p=p) for i, p in enumerate(values)
    ]


def spikes(moves):
    return [m for m in moves if m.kind == "spike"]


class TestCreationWindow:
    def test_a_flat_market_still_offers_the_window_it_opened_in(self):
        """
        A market that never moved is not a market with no story — it is usually
        one whose story was told before it opened. The origin stage must always
        have somewhere to look.
        """
        moves = detect_sharp_moves(series([0.4] * 40), START)

        assert spikes(moves) == []
        assert [m.kind for m in moves] == ["creation"]

    def test_with_no_creation_date_a_flat_market_yields_nothing(self):
        """Better to report no window than to invent one."""
        assert detect_sharp_moves(series([0.4] * 40), None) == []


class TestDetection:
    def test_a_single_step_is_reported_once(self):
        moves = spikes(detect_sharp_moves(series([0.30] * 20 + [0.55] * 20), START))

        assert len(moves) == 1
        assert moves[0].delta > MIN_DELTA

    def test_the_delta_is_in_points_not_percent(self):
        """
        0.02 to 0.04 is a 100% rise and two cents of noise; 0.45 to 0.62 is the
        one that had a cause. Ranking by percentage puts every long shot above
        every real event.
        """
        moves = spikes(detect_sharp_moves(series([0.45] * 20 + [0.62] * 20), START))

        assert moves[0].delta == 0.17

    def test_a_move_within_a_day_of_a_bigger_one_is_the_same_event(self):
        """
        One event produces a cluster of overlapping six-hour windows. Reporting
        all of them spends the search budget asking the same question twice.
        """
        values = [0.20] * 10 + [0.50] * 6 + [0.62] * 24
        moves = spikes(detect_sharp_moves(series(values), START))

        assert len(moves) == 1

    def test_two_events_a_week_apart_are_both_reported(self):
        values = [0.20] * 10 + [0.45] * 168 + [0.70] * 20
        moves = spikes(detect_sharp_moves(series(values), START))

        assert len(moves) == 2

    def test_a_market_that_swings_all_day_does_not_report_its_churn(self):
        """
        The absolute floor alone flags everything on a volatile market. A
        candidate also has to stand clear of this market's own median move,
        which is what keeps the detector useful on a jumpy question.
        """
        values = [0.30 + (0.12 if i % 2 else -0.12) for i in range(80)]
        moves = spikes(detect_sharp_moves(series(values), START))

        assert moves == []

    def test_a_small_move_on_a_quiet_market_is_still_not_news(self):
        """The relative test is a floor raiser, never a floor lowerer."""
        moves = spikes(detect_sharp_moves(series([0.400] * 20 + [0.415] * 20), START))

        assert moves == []

    def test_no_more_than_three_windows_are_offered(self):
        values: list[float] = []
        for level in (0.10, 0.30, 0.50, 0.70, 0.90):
            values += [level] * 48
        moves = spikes(detect_sharp_moves(series(values), START))

        assert len(moves) <= 3


class TestRobustness:
    def test_unsorted_and_duplicated_history_is_handled(self):
        """
        The upstream is paginated and occasionally repeats a timestamp across
        page boundaries. A duplicate must not read as a zero-second move.
        """
        points = series([0.30] * 20 + [0.55] * 20)
        scrambled = list(reversed(points)) + points[:5]

        moves = spikes(detect_sharp_moves(scrambled, START))

        assert len(moves) == 1

    def test_a_history_shorter_than_the_window_reports_no_spike(self):
        moves = detect_sharp_moves(series([0.1, 0.9]), START)

        assert spikes(moves) == []

    def test_an_empty_history_does_not_raise(self):
        assert [m.kind for m in detect_sharp_moves([], START)] == ["creation"]
