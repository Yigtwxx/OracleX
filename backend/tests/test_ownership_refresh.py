"""
What a refresh does with the sources it did not read.

Two ways a position can be absent from a run: the source was not asked (a
partial, intraday run) or it was asked and failed. Both used to end the same
way — the position vanished and the card lost its total — and both are wrong in
the same direction, because "we did not look" is not "they do not hold it".
"""

from datetime import UTC, date, datetime

from models.ownership import Position, SourceRef
from services.ownership.providers.base import ProviderResult
from services.ownership.refresh import _carried_results, _carry_failed


def _stored(key: str, kind: str, value: float) -> dict:
    return Position(
        key=key,
        label=key.upper(),
        symbol=key.upper(),
        asset_class="crypto",
        quantity=1.0,
        quantity_unit=key.upper(),
        value_usd=value,
        value_basis="marked",
        source=SourceRef(
            kind=kind,
            label="Last reading",
            as_of=date(2026, 8, 10),
            retrieved_at=datetime.now(UTC),
        ),
    ).model_dump(mode="json")


def test_sources_a_partial_run_did_not_ask_are_carried_forward():
    stored = [_stored("btc", "coingecko_treasury", 100.0), _stored("cash", "manual", 50.0)]

    carried = _carried_results(stored, skipped_kinds={"manual"})

    assert [r.kind for r in carried] == ["manual"]
    assert carried[0].positions[0].value_usd == 50.0
    # The carried position keeps the date it was read on, not today's.
    assert carried[0].positions[0].source.as_of == date(2026, 8, 10)


def test_a_failed_source_falls_back_to_its_last_reading_and_flags_the_entity():
    stored = [_stored("btc", "coingecko_treasury", 100.0)]
    results = [ProviderResult.failed("coingecko_treasury", "429 rate limited")]

    repaired, carried = _carry_failed(results, stored)

    assert carried is True
    assert repaired[0].ok is True
    assert repaired[0].positions[0].value_usd == 100.0
    # The reason survives as an issue: the card is showing an older reading and
    # has to be able to say why.
    assert "429" in (repaired[0].error or "")


def test_a_failed_source_with_nothing_stored_stays_failed():
    # No previous reading means there is nothing honest to show. The entity
    # keeps its card and an unknown total rather than a borrowed number.
    results = [ProviderResult.failed("onchain", "host unreachable")]

    repaired, carried = _carry_failed(results, [])

    assert carried is False
    assert repaired[0].ok is False


def test_a_successful_run_carries_nothing():
    stored = [_stored("btc", "coingecko_treasury", 100.0)]
    fresh = ProviderResult(kind="coingecko_treasury", ok=True, positions=[])

    repaired, carried = _carry_failed([fresh], stored)

    assert carried is False
    assert repaired == [fresh]
