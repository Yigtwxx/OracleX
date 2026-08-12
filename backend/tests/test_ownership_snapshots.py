"""
The snapshot diff, which is the easiest thing in this feature to get silently
wrong.

Every assertion here is about a way the board could publish a false statement:
a delta invented against no baseline, the same filing re-announced every morning
for a quarter, a price move reported as a purchase, or a parser regression
announced as a holder liquidating and rebuilding overnight.
"""

from datetime import UTC, datetime, timedelta

import pytest

from models.ownership import Position, SourceRef
from services.ownership import snapshots
from services.ownership.providers.base import EntityConfig


@pytest.fixture(autouse=True)
def isolated_snapshot_file(tmp_path, monkeypatch):
    """Never touch the real history file from a test run."""
    monkeypatch.setattr(snapshots, "SNAPSHOT_FILE", str(tmp_path / "ownership_snapshots.json"))


def _position(
    key: str,
    quantity: float,
    *,
    value_usd: float | None = None,
    asset_class: str = "crypto",
) -> Position:
    return Position(
        key=key,
        label=key.title(),
        symbol=key.upper()[:3],
        asset_class=asset_class,  # type: ignore[arg-type]
        quantity=quantity,
        quantity_unit=key.upper()[:3],
        value_usd=value_usd,
        value_basis="marked" if value_usd is not None else "unknown",
        source=SourceRef(kind="coingecko_treasury", label="Test", retrieved_at=datetime.now(UTC)),
    )


def _entity(category: str = "treasury") -> EntityConfig:
    return EntityConfig(
        id="acme",
        name="Acme Corp",
        subtitle="ACME",
        category=category,
        country="US",
        coverage_note=None,
        sources={"coingecko_treasury": {"symbol": "ACME.US", "coins": ["bitcoin"]}},
    )


def _at(days_ago: int = 0) -> datetime:
    return datetime.now(UTC) - timedelta(days=days_ago)


# ── Baseline ────────────────────────────────────────────────────────────────


def test_first_observation_produces_no_moves():
    history = snapshots.load()

    moves = snapshots.diff_and_append(history, _entity(), [_position("bitcoin", 100.0)], _at())

    # Deltas against nothing would announce that this holder just bought
    # everything it owns.
    assert moves == []
    assert snapshots.has_baseline(history, "acme") is True


def test_has_baseline_is_false_before_any_observation():
    assert snapshots.has_baseline(snapshots.load(), "acme") is False


# ── Change detection ────────────────────────────────────────────────────────


def test_identical_reading_is_not_recorded_again():
    history = snapshots.load()
    entity = _entity()
    positions = [_position("bitcoin", 100.0)]

    snapshots.diff_and_append(history, entity, positions, _at(2))
    moves = snapshots.diff_and_append(history, entity, positions, _at(1))

    assert moves == []
    # The ceiling that keeps a quarterly filing from writing 90 observations.
    assert len(history["entities"]["acme"]["observations"]) == 1


def test_price_only_change_is_not_a_purchase():
    history = snapshots.load()
    entity = _entity()

    snapshots.diff_and_append(
        history, entity, [_position("bitcoin", 100.0, value_usd=1_000)], _at(2)
    )
    # Same coins, different market. Nobody bought anything.
    moves = snapshots.diff_and_append(
        history, entity, [_position("bitcoin", 100.0, value_usd=2_000)], _at(1)
    )

    assert moves == []


def test_sub_threshold_quantity_drift_is_rounding_not_a_trade():
    history = snapshots.load()
    entity = _entity()

    snapshots.diff_and_append(history, entity, [_position("bitcoin", 100_000.0)], _at(2))
    # One basis point — below CHANGE_EPSILON.
    moves = snapshots.diff_and_append(history, entity, [_position("bitcoin", 100_010.0)], _at(1))

    assert moves == []


# ── Move kinds ──────────────────────────────────────────────────────────────


def test_increase_and_decrease_for_a_treasury():
    history = snapshots.load()
    entity = _entity("treasury")

    snapshots.diff_and_append(history, entity, [_position("bitcoin", 100.0)], _at(3))
    up = snapshots.diff_and_append(history, entity, [_position("bitcoin", 150.0)], _at(2))
    down = snapshots.diff_and_append(history, entity, [_position("bitcoin", 120.0)], _at(1))

    assert [m.kind for m in up] == ["increase"]
    assert up[0].quantity_delta == pytest.approx(50.0)
    assert [m.kind for m in down] == ["decrease"]
    assert down[0].quantity_delta == pytest.approx(-30.0)


def test_add_and_trim_for_an_institution():
    history = snapshots.load()
    entity = _entity("institution")

    snapshots.diff_and_append(history, entity, [_position("aapl", 100.0)], _at(3))
    up = snapshots.diff_and_append(history, entity, [_position("aapl", 150.0)], _at(2))
    down = snapshots.diff_and_append(history, entity, [_position("aapl", 50.0)], _at(1))

    # A fund adds and trims; a treasury increases and reduces. Same arithmetic,
    # different readers.
    assert [m.kind for m in up] == ["add"]
    assert [m.kind for m in down] == ["trim"]


def test_new_and_exit_positions():
    history = snapshots.load()
    entity = _entity("institution")

    snapshots.diff_and_append(history, entity, [_position("aapl", 100.0)], _at(3))
    opened = snapshots.diff_and_append(
        history, entity, [_position("aapl", 100.0), _position("googl", 20.0)], _at(2)
    )
    closed = snapshots.diff_and_append(history, entity, [_position("googl", 20.0)], _at(1))

    assert [m.kind for m in opened] == ["new"]
    assert opened[0].asset_label == "Googl"
    assert [m.kind for m in closed] == ["exit"]
    # An exit is a negative delta — the holder disposed of what it held.
    assert closed[0].quantity_delta == pytest.approx(-100.0)


# ── Deduplication ───────────────────────────────────────────────────────────


def test_the_same_event_gets_the_same_id_so_it_is_published_once():
    history_a = snapshots.load()
    history_b = snapshots.load()
    entity = _entity()
    when = _at(1)

    snapshots.diff_and_append(history_a, entity, [_position("bitcoin", 100.0)], _at(2))
    first = snapshots.diff_and_append(history_a, entity, [_position("bitcoin", 150.0)], when)

    snapshots.diff_and_append(history_b, entity, [_position("bitcoin", 100.0)], _at(2))
    second = snapshots.diff_and_append(history_b, entity, [_position("bitcoin", 150.0)], when)

    assert first[0].id == second[0].id


def test_record_events_drops_moves_already_stored():
    history = snapshots.load()
    entity = _entity()

    snapshots.diff_and_append(history, entity, [_position("bitcoin", 100.0)], _at(2))
    moves = snapshots.diff_and_append(history, entity, [_position("bitcoin", 150.0)], _at(1))

    assert len(snapshots.record_events(history, moves)) == 1
    # A provider re-serving its last-30-days window must not grow the feed.
    assert snapshots.record_events(history, moves) == []
    assert len(snapshots.stored_moves(history, "acme")) == 1


# ── Guards ──────────────────────────────────────────────────────────────────


def test_implausible_turnover_is_suppressed_and_rebaselined():
    history = snapshots.load()
    entity = _entity("institution")
    before = [_position(f"stock{i}", 10.0) for i in range(10)]
    # Every key changed — what a CUSIP-to-ticker parser regression looks like.
    after = [_position(f"ticker{i}", 10.0) for i in range(10)]

    snapshots.diff_and_append(history, entity, before, _at(2))
    moves = snapshots.diff_and_append(history, entity, after, _at(1))

    assert moves == []
    latest = history["entities"]["acme"]["observations"][-1]
    assert latest["suppressed"] == "implausible turnover"
    # The new reading is still stored, so tomorrow diffs against reality.
    assert set(latest["positions"]) == {f"ticker{i}" for i in range(10)}


def test_observations_are_capped():
    history = snapshots.load()
    entity = _entity()

    for i in range(snapshots.MAX_OBSERVATIONS + 5):
        snapshots.diff_and_append(
            history, entity, [_position("bitcoin", 100.0 + i * 10)], _at(20 - i)
        )

    snapshots.save(history)
    assert len(history["entities"]["acme"]["observations"]) == snapshots.MAX_OBSERVATIONS


def test_history_survives_a_save_and_reload():
    history = snapshots.load()
    entity = _entity()

    snapshots.diff_and_append(history, entity, [_position("bitcoin", 100.0)], _at(2))
    moves = snapshots.diff_and_append(history, entity, [_position("bitcoin", 150.0)], _at(1))
    snapshots.record_events(history, moves)
    snapshots.save(history)

    reloaded = snapshots.load()
    assert snapshots.has_baseline(reloaded, "acme") is True
    assert len(snapshots.stored_moves(reloaded, "acme")) == 1


def test_change_with_neither_quantity_nor_value_is_not_published():
    history = snapshots.load()
    entity = _entity()

    first = Position(
        key="mystery",
        label="Mystery",
        asset_class="other",
        quantity=None,
        value_usd=None,
        source=SourceRef(kind="manual", label="Test"),
    )
    second = first.model_copy(update={"label": "Mystery II"})

    snapshots.diff_and_append(history, entity, [first], _at(2))
    moves = snapshots.diff_and_append(history, entity, [second], _at(1))

    # "It changed, amount unknown" is not a fact worth publishing.
    assert moves == []


def test_moves_carry_the_source_of_the_positions_they_came_from():
    history = snapshots.load()
    entity = _entity()
    observed = _at(1)

    snapshots.diff_and_append(history, entity, [_position("bitcoin", 100.0)], _at(2))
    moves = snapshots.diff_and_append(history, entity, [_position("bitcoin", 150.0)], observed)

    # A derived move has no filing of its own; inventing a source would be worse
    # than inheriting one.
    assert moves[0].source.kind == "coingecko_treasury"
    # Dated to when we observed it, not to today.
    assert moves[0].occurred_at == observed.date()


def test_single_position_treasury_still_reports_its_moves():
    """The turnover guard must not swallow the entities it was never about."""
    history = snapshots.load()
    entity = _entity("treasury")

    snapshots.diff_and_append(history, entity, [_position("bitcoin", 100.0)], _at(2))
    moves = snapshots.diff_and_append(history, entity, [_position("bitcoin", 5_100.0)], _at(1))

    # 100% of its positions changed, because it only has one. That is the event,
    # not a red flag.
    assert [m.kind for m in moves] == ["increase"]


def test_partial_key_overlap_in_a_large_portfolio_is_not_suppressed():
    history = snapshots.load()
    entity = _entity("institution")
    before = [_position(f"stock{i}", 10.0) for i in range(10)]
    # Three exits, three entries, seven holdings untouched — an ordinary quarter.
    after = [_position(f"stock{i}", 10.0) for i in range(3, 10)] + [
        _position(f"new{i}", 5.0) for i in range(3)
    ]

    snapshots.diff_and_append(history, entity, before, _at(2))
    moves = snapshots.diff_and_append(history, entity, after, _at(1))

    assert len(moves) == 6
    assert history["entities"]["acme"]["observations"][-1].get("suppressed") is None


# ── Backfill vs. real event ─────────────────────────────────────────────────


def _manual_position(key: str, value_usd: float) -> Position:
    return Position(
        key=key,
        label="Cash & cash equivalents",
        asset_class="cash",
        quantity=value_usd,
        quantity_unit="USD",
        value_usd=value_usd,
        value_basis="reported",
        source=SourceRef(kind="manual", label="10-Q", url="https://sec.gov/x", manual=True),
    )


def test_a_new_source_backfills_silently_rather_than_announcing_a_purchase():
    history = snapshots.load()
    entity = _entity()

    snapshots.diff_and_append(history, entity, [_position("bitcoin", 100.0)], _at(2))
    # A manual cash row is added to the registry. Nobody acquired anything.
    moves = snapshots.diff_and_append(
        history,
        entity,
        [_position("bitcoin", 100.0), _manual_position("cash:USD", 1_000.0)],
        _at(1),
    )

    assert moves == []
    # The level is still recorded, so tomorrow's change against it is real.
    assert "cash:USD" in history["entities"]["acme"]["observations"][-1]["positions"]


def test_a_change_after_a_backfill_is_a_real_move():
    history = snapshots.load()
    entity = _entity()

    snapshots.diff_and_append(history, entity, [_position("bitcoin", 100.0)], _at(3))
    snapshots.diff_and_append(
        history,
        entity,
        [_position("bitcoin", 100.0), _manual_position("cash:USD", 1_000.0)],
        _at(2),
    )
    moves = snapshots.diff_and_append(
        history, entity, [_position("bitcoin", 100.0), _manual_position("cash:USD", 600.0)], _at(1)
    )

    # The next 10-Q showing less cash *is* news.
    assert [m.kind for m in moves] == ["decrease"]
    assert moves[0].quantity_delta == pytest.approx(-400.0)


def test_a_removed_source_does_not_read_as_a_disposal():
    history = snapshots.load()
    entity = _entity()

    snapshots.diff_and_append(history, entity, [_position("bitcoin", 100.0)], _at(3))
    snapshots.diff_and_append(
        history,
        entity,
        [_position("bitcoin", 100.0), _manual_position("cash:USD", 1_000.0)],
        _at(2),
    )
    # The manual group is deleted from the registry.
    moves = snapshots.diff_and_append(history, entity, [_position("bitcoin", 100.0)], _at(1))

    assert moves == []


def test_a_new_key_from_an_already_running_source_is_a_real_position():
    history = snapshots.load()
    entity = _entity("institution")

    snapshots.diff_and_append(history, entity, [_position("aapl", 100.0)], _at(2))
    # Same provider, one more holding. That is the holder buying something.
    moves = snapshots.diff_and_append(
        history, entity, [_position("aapl", 100.0), _position("googl", 50.0)], _at(1)
    )

    assert [m.kind for m in moves] == ["new"]
