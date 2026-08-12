"""
Ownership board behaviour, pinned without touching the network.

The rules under test are the ones that make this page trustworthy rather than
merely populated, and every one of them fails silently if it regresses: a total
that quietly counts an unknown as zero, a weight computed against a denominator
we do not know, an outage that empties the grid and reads as everyone selling.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from models.ownership import Position, SourceRef
from services.ownership import board as board_module
from services.ownership import registry
from services.ownership.providers.base import EntityConfig, ProviderResult


def _source(label: str = "Test source", as_of: date | None = None) -> SourceRef:
    return SourceRef(
        kind="coingecko_treasury",
        label=label,
        as_of=as_of,
        retrieved_at=datetime.now(UTC),
    )


def _position(
    key: str,
    value_usd: float | None,
    *,
    asset_class: str = "crypto",
    quantity: float = 1.0,
    as_of: date | None = None,
) -> Position:
    return Position(
        key=key,
        label=key.upper(),
        symbol=key.upper(),
        asset_class=asset_class,  # type: ignore[arg-type]
        quantity=quantity,
        quantity_unit=key.upper(),
        value_usd=value_usd,
        value_basis="marked" if value_usd is not None else "unknown",
        source=_source(as_of=as_of),
    )


def _entity(entity_id: str = "acme", category: str = "treasury") -> EntityConfig:
    return EntityConfig(
        id=entity_id,
        name="Acme Corp",
        subtitle="ACME",
        category=category,
        country="US",
        coverage_note="Balance sheet only.",
        sources={"coingecko_treasury": {"symbol": "ACME.US", "coins": ["bitcoin"]}},
    )


def _ok(positions: list[Position]) -> ProviderResult:
    return ProviderResult(kind="coingecko_treasury", ok=True, positions=positions)


@pytest.fixture(autouse=True)
def isolated_board_store(tmp_path, monkeypatch):
    """
    Point the board's disk and memory stores at throwaway state.

    Without this, `store_board` writes the real backend/data/registry board file
    and leaves a two-entity fixture where the app expects its own data — a test
    run would quietly replace what the page serves.
    """
    monkeypatch.setattr(board_module, "BOARD_FILE", str(tmp_path / "ownership_board.json"))
    board_module.ownership_cache.invalidate(board_module.BOARD_CACHE_KEY)
    yield
    board_module.ownership_cache.clear()


# ── Totals and weights ──────────────────────────────────────────────────────


def test_unpriced_position_is_excluded_from_total_not_counted_as_zero():
    summary, _ = board_module.build_entity_summary(
        _entity(), [_ok([_position("btc", 100.0), _position("eth", None)])]
    )

    assert summary.total_value_usd == 100.0
    assert summary.positions_count == 2
    # The card has to admit the total is partial rather than present $100 as
    # the whole picture.
    assert any("no published USD value" in issue for issue in summary.issues)


def test_entity_with_nothing_priced_has_unknown_total_not_zero():
    summary, _ = board_module.build_entity_summary(
        _entity(), [_ok([_position("btc", None), _position("eth", None)])]
    )

    assert summary.total_value_usd is None
    assert summary.has_data is True
    # No priced value means no bar — an "other" segment drawn full width would
    # invent a composition out of missing data.
    assert summary.allocation == []


def test_weights_are_absent_when_the_denominator_is_unknown():
    _, positions = board_module.build_entity_summary(_entity(), [_ok([_position("btc", None)])])

    assert positions[0].weight_pct is None


def test_weights_are_computed_against_the_known_total():
    _, positions = board_module.build_entity_summary(
        _entity(), [_ok([_position("btc", 75.0), _position("eth", 25.0)])]
    )

    by_key = {p.key: p for p in positions}
    assert by_key["btc"].weight_pct == pytest.approx(75.0)
    assert by_key["eth"].weight_pct == pytest.approx(25.0)


# ── Allocation ──────────────────────────────────────────────────────────────


def test_allocation_is_one_slice_per_holding_and_sums_to_100():
    summary, _ = board_module.build_entity_summary(
        _entity(),
        [
            _ok(
                [
                    _position("btc", 50.0, asset_class="crypto"),
                    _position("eth", 30.0, asset_class="crypto"),
                    _position("cash", 20.0, asset_class="cash"),
                ]
            )
        ],
    )

    slices = {s.key: s for s in summary.allocation}
    # Two crypto holdings stay two segments. Merged, they would draw the same
    # bar as a treasury holding only bitcoin.
    assert slices["btc"].pct == pytest.approx(50.0)
    assert slices["eth"].pct == pytest.approx(30.0)
    assert slices["cash"].pct == pytest.approx(20.0)
    assert slices["eth"].label == "ETH"
    assert slices["eth"].symbol == "ETH"
    # Largest first, so the bar reads left to right by size.
    assert summary.allocation[0].key == "btc"


def test_allocation_disambiguates_two_share_classes_of_one_issuer():
    goog = _position("goog", 60.0, asset_class="equity")
    goog.label = "Alphabet Inc"
    googl = _position("googl", 40.0, asset_class="equity")
    googl.label = "Alphabet Inc"

    summary, _ = board_module.build_entity_summary(_entity(), [_ok([goog, googl])])

    labels = [s.label for s in summary.allocation]
    assert labels == ["Alphabet Inc (GOOG)", "Alphabet Inc (GOOGL)"]


def test_allocation_pools_the_tail_past_the_named_slices():
    positions = [_position(f"h{i}", float(20 - i)) for i in range(10)]
    summary, _ = board_module.build_entity_summary(_entity(), [_ok(positions)])

    named = board_module.TOP_ALLOCATION_SLICES
    assert len(summary.allocation) == named + 1

    pooled = summary.allocation[-1]
    assert pooled.key == "__other__"
    assert pooled.label == f"{len(positions) - named} smaller holdings"
    # The pooled segment is the rest of the value, not a rounding remainder.
    assert sum(s.pct for s in summary.allocation) == pytest.approx(100.0)


# ── Failure handling ────────────────────────────────────────────────────────


def test_entity_survives_a_failed_source_and_is_flagged_stale():
    failed = ProviderResult.failed("coingecko_treasury", "429 rate limited")
    summary, positions = board_module.build_entity_summary(_entity(), [failed])

    # The card stays on the grid. One that vanished would read as "sold
    # everything", which is a claim the outage does not license.
    assert summary.stale is True
    assert summary.has_data is False
    assert summary.total_value_usd is None
    assert positions == []
    assert any("429" in issue for issue in summary.issues)


def test_partial_provider_success_reports_what_it_missed():
    partial = ProviderResult(
        kind="coingecko_treasury",
        ok=True,
        positions=[_position("btc", 10.0)],
        error="ethereum: ACME.US not listed",
    )
    summary, _ = board_module.build_entity_summary(_entity(), [partial])

    assert summary.has_data is True
    assert summary.stale is False
    assert any("not listed" in issue for issue in summary.issues)


def test_source_is_unhealthy_only_when_every_entity_failed():
    resolved = {
        "a": [ProviderResult.failed("coingecko_treasury", "boom")],
        "b": [_ok([_position("btc", 1.0)])],
    }
    health = board_module._source_health(resolved, datetime.now(UTC))

    assert len(health) == 1
    # One entity failing is a bad registry key, not an outage.
    assert health[0].ok is True
    assert health[0].entities_covered == 1


# ── Card metadata ───────────────────────────────────────────────────────────


def test_card_as_of_is_the_oldest_source_date():
    summary, _ = board_module.build_entity_summary(
        _entity(),
        [
            _ok(
                [
                    _position("btc", 10.0, as_of=date(2026, 6, 30)),
                    _position("eth", 10.0, as_of=date(2025, 12, 31)),
                ]
            )
        ],
    )

    # A card summarising a stale filing and a live price is only as current as
    # the stale filing.
    assert summary.as_of == date(2025, 12, 31)


def test_top_positions_rank_unpriced_last_not_as_zero():
    summary, _ = board_module.build_entity_summary(
        _entity(),
        [_ok([_position("small", 1.0), _position("unknown", None), _position("big", 100.0)])],
    )

    assert [p.key for p in summary.top_positions] == ["big", "small", "unknown"]


def test_board_counts_categories():
    entities = [_entity("a", "treasury"), _entity("b", "treasury"), _entity("c", "institution")]
    resolved = {e.id: [_ok([_position("btc", 1.0)])] for e in entities}

    board, positions_by_entity = board_module.build_board(entities, resolved, datetime.now(UTC))

    assert board.category_counts == {"treasury": 2, "institution": 1}
    assert set(positions_by_entity) == {"a", "b", "c"}
    assert board.stale is False


# ── Staleness ───────────────────────────────────────────────────────────────


def _store_board_aged(hours_old: float) -> None:
    """Persist a board whose last refresh was `hours_old` hours ago."""
    built = datetime.now(UTC) - timedelta(hours=hours_old)
    entities = [_entity()]
    resolved = {"acme": [_ok([_position("btc", 1.0)])]}
    board, positions = board_module.build_board(entities, resolved, built)
    board_module.store_board(board, positions)


def test_board_freshly_built_is_not_stale():
    _store_board_aged(1)
    assert board_module.get_board().stale is False


def test_old_board_stays_stale_across_repeated_reads():
    _store_board_aged(48)

    # Read twice. The first read is what used to re-seed the memory cache from
    # disk, which made every later read look fresh however old the board was.
    first = board_module.get_board()
    second = board_module.get_board()

    assert first.stale is True
    assert second.stale is True


def test_board_without_a_refresh_timestamp_is_stale():
    _store_board_aged(1)
    payload = board_module._load_payload()
    assert payload is not None
    payload["board"]["last_refresh_at"] = None
    board_module.ownership_cache.set(
        board_module.BOARD_CACHE_KEY, payload, board_module.BOARD_TTL_SECONDS
    )

    assert board_module.get_board().stale is True


# ── Icons ───────────────────────────────────────────────────────────────────
# Which mark a card shows is a claim about what identifies the holder, so the
# wrong one is not a cosmetic slip: a logo on a politician invents a brand for
# a person in office, and a borrowed logo on a fund we have nothing for asserts
# an identity we cannot back.


def test_listed_company_is_drawn_by_its_ticker():
    url = registry.entity_logo_url(_entity())
    assert url == "https://financialmodelingprep.com/image-stock/ACME.png"


def test_non_us_listing_keeps_its_exchange_suffix():
    entity = _entity()
    entity.sources = {"coingecko_treasury": {"symbol": "3350.T", "coins": ["bitcoin"]}}

    # Stripping the suffix would ask for "3350", which resolves somewhere else
    # entirely rather than failing loudly.
    assert registry.entity_logo_url(entity) == (
        "https://financialmodelingprep.com/image-stock/3350.T.png"
    )


def test_fund_without_a_ticker_is_drawn_by_its_registered_domain():
    entity = _entity(category="institution")
    entity.sources = {"sec_13f": {"cik": "0001067983"}}
    entity.logo_domain = "bridgewater.com"

    assert registry.entity_logo_url(entity) == (
        "https://www.google.com/s2/favicons?domain=bridgewater.com&sz=128"
    )


def test_politician_has_no_logo_so_the_card_keeps_its_flag():
    entity = _entity(category="politician")
    entity.logo_domain = "example.com"

    assert registry.entity_logo_url(entity) is None


def test_holder_with_nothing_to_draw_from_has_no_logo():
    entity = _entity(category="institution")
    entity.sources = {"sec_13f": {"cik": "0001067983"}}

    # None is a real answer: the card falls back to a monogram rather than
    # borrowing a mark that belongs to someone else.
    assert registry.entity_logo_url(entity) is None


def test_stored_board_picks_up_the_current_registry_icon(monkeypatch):
    _store_board_aged(1)

    # A board on disk can be a day old, or a week through an outage. The icon
    # still comes from the registry as it is now — a corrected logo must not
    # wait for the numbers to rebuild before it reaches the card.
    monkeypatch.setattr(registry, "load_entities", lambda: [_entity()])

    served = board_module.get_board()
    assert served.entities[0].logo_url == ("https://financialmodelingprep.com/image-stock/ACME.png")
