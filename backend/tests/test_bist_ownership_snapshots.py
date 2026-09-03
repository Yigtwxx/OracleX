"""
Daily snapshots of the shareholder tables, and the changes read off them.

What is pinned is what the module refuses to claim: a holder present on the
first day has no entry date, a ticker absent from one side of a comparison
produces no moves, a failed card is not written as an empty table, and a
change under the card's own rounding is not a trade.
"""

import os

import pytest

from services.bist.ownership import snapshots
from services.cache import bist_cache


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    bist_cache.clear()
    monkeypatch.setattr(snapshots, "SNAPSHOT_FILE", os.path.join(tmp_path, "snapshots.json"))
    yield
    bist_cache.clear()


def _row(*holders: tuple[str, float], ok: bool = True, carried: bool = False) -> dict:
    return {
        "ok": ok,
        "carried": carried,
        "holders": [{"label": label, "stake_pct": stake} for label, stake in holders],
    }


def test_record_keeps_only_fresh_successful_cards():
    snapshots.record(
        "2026-09-02",
        {
            "THYAO": _row(("TVF", 0.4912)),
            "KRDMD": _row(),
            "FAILED": _row(ok=False),
            "CARRIED": _row(("X", 0.5), carried=True),
        },
    )

    tables = snapshots.tables_for("2026-09-02")
    assert tables == {"THYAO": {"TVF": 0.4912}, "KRDMD": {}}
    assert snapshots.days() == ["2026-09-02"]
    assert snapshots.baseline_day() == "2026-09-02"


def test_a_second_refresh_on_the_same_day_overwrites():
    snapshots.record("2026-09-02", {"THYAO": _row(("TVF", 0.4912))})
    snapshots.record("2026-09-02", {"THYAO": _row(("TVF", 0.50))})

    assert snapshots.tables_for("2026-09-02") == {"THYAO": {"TVF": 0.50}}


def test_changes_name_entries_exits_and_resizes():
    earlier = {"THYAO": {"TVF": 0.4912, "Gone": 0.06}, "ONLY_BEFORE": {"A": 0.1}}
    later = {"THYAO": {"TVF": 0.52, "Fresh": 0.055}, "ONLY_AFTER": {"B": 0.2}}

    changes = snapshots.changes_between(earlier, later, "2026-09-03")

    assert [(c.holder, c.kind) for c in changes] == [
        ("Fresh", "new"),
        ("Gone", "exit"),
        ("TVF", "add"),
    ]
    assert all(c.ticker == "THYAO" for c in changes), "unpaired tickers produce nothing"
    assert changes[2].stake_before == 0.4912 and changes[2].stake_after == 0.52


def test_rounding_noise_is_not_a_trade():
    changes = snapshots.changes_between(
        {"THYAO": {"TVF": 0.4912}}, {"THYAO": {"TVF": 0.4913}}, "2026-09-03"
    )
    assert changes == []


def test_history_distinguishes_baseline_from_a_real_entry():
    snapshots.record("2026-09-02", {"THYAO": _row(("TVF", 0.4912))})
    snapshots.record("2026-09-03", {"THYAO": _row(("TVF", 0.4912), ("Fresh", 0.055))})
    snapshots.record("2026-09-04", {"THYAO": _row(("TVF", 0.50), ("Fresh", 0.055))})

    tvf = snapshots.history_for("THYAO", "TVF")
    assert tvf is not None
    assert tvf.first_seen == "2026-09-02" and tvf.at_baseline
    assert tvf.previous_stake == 0.4912

    fresh = snapshots.history_for("THYAO", "Fresh")
    assert fresh is not None
    assert fresh.first_seen == "2026-09-03" and not fresh.at_baseline

    assert snapshots.history_for("THYAO", "Nobody") is None
    assert snapshots.history_for("OTHER", "TVF") is None


def test_a_holder_that_leaves_and_returns_enters_again():
    snapshots.record("2026-09-02", {"THYAO": _row(("X", 0.06))})
    snapshots.record("2026-09-03", {"THYAO": _row()})
    snapshots.record("2026-09-04", {"THYAO": _row(("X", 0.07))})

    history = snapshots.history_for("THYAO", "X")
    assert history is not None
    assert history.first_seen == "2026-09-04" and not history.at_baseline
    assert [(c.kind, c.observed_at) for c in snapshots.all_changes()] == [
        ("new", "2026-09-04"),
        ("exit", "2026-09-03"),
    ]


def test_a_day_the_ticker_was_not_fetched_does_not_break_the_run():
    snapshots.record("2026-09-02", {"THYAO": _row(("TVF", 0.4912))})
    snapshots.record("2026-09-03", {"OTHER": _row(("Y", 0.1))})
    snapshots.record("2026-09-04", {"THYAO": _row(("TVF", 0.4912))})

    history = snapshots.history_for("THYAO", "TVF")
    assert history is not None
    assert history.first_seen == "2026-09-02" and history.at_baseline
    assert snapshots.all_changes() == []


def test_retention_drops_the_oldest_days(monkeypatch):
    monkeypatch.setattr(snapshots, "RETENTION_DAYS", 2)
    for day in ("2026-09-01", "2026-09-02", "2026-09-03"):
        snapshots.record(day, {"THYAO": _row(("TVF", 0.5))})

    assert snapshots.days() == ["2026-09-02", "2026-09-03"]
