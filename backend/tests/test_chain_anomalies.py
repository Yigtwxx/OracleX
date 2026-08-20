"""
The chain baseline and the anomaly detector.

`test_chains.py` next door tests pure helpers with literal data and no fixtures
at all. These two modules cannot quite live by that rule — one owns a file and
the other reads a clock — so they get their own file, with the two fixtures they
genuinely need and nothing more. Everything else follows the same conventions:
private functions called directly, hand-built rows, and a docstring naming the
regression each case guards.

The recurring theme is refusal. Most of what follows asserts that the detector
declines to judge — a span too short to be a trend, a baseline drawn from one
afternoon, a chain that could not be read at all. An anomaly detector that always
finds something is worth less than one that admits when it cannot tell.
"""

from datetime import UTC, datetime

import pytest

from services import ai_notes
from services.chains import anomaly, flows, history

NOON = datetime(2026, 8, 18, 12, 0, tzinfo=UTC).timestamp()
DAY = 24 * 3600


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "STORE_FILE", str(tmp_path / "chain_metrics.json"))
    history.reset_state()
    monkeypatch.setattr(flows, "_series", {})
    yield
    history.reset_state()


def _seed(key: str, rows: list[tuple[float, dict]]) -> None:
    """Push samples straight into the store, bypassing the interval gate."""
    with history._lock:
        history._load()[key] = [{"t": t, **fields} for t, fields in rows]


def _fees(key: str, *, days: int, value: float, hour_offset: float = 0.0) -> None:
    _seed(
        key,
        [
            (NOON - day * DAY + hour_offset * 3600, {"fee_native": value})
            for day in range(1, days + 1)
        ],
    )


def _row(key: str, **overrides) -> dict:
    row = {"key": key, "name": key.title(), "error": None}
    row.update(overrides)
    return row


def _board(*rows: dict) -> dict:
    return {"chains": list(rows), "as_of": "2026-08-18T12:00:00+00:00", "stale": False}


# ── history: sampling ────────────────────────────────────────────────────────


async def test_the_board_is_sampled_at_most_once_a_quarter_hour():
    """
    The board's own cache is ten seconds and every open tab polls it. Without the
    gate a single busy page would rewrite the store hundreds of times an hour to
    record readings that had barely moved.
    """
    board = _board(_row("ethereum", fee={"transfer_native": 0.001}))

    await history.record(board)
    await history.record(board)
    await history.record(board)

    assert history.coverage()["ethereum"] == 1


async def test_an_unreachable_chain_is_not_a_cheap_one():
    """
    A failed row carries blank readings, and a blank is not a low fee. Letting one
    into the median would drag the baseline down and manufacture a spike on the
    next successful read.
    """
    await history.record(_board(_row("base", error="timeout", fee={"transfer_native": None})))
    assert "base" not in history.coverage()


async def test_history_survives_a_reload():
    await history.record(_board(_row("ethereum", fee={"transfer_native": 0.002})))
    history.reset_state()
    assert history.coverage()["ethereum"] == 1


def test_samples_past_the_retention_window_are_dropped():
    rows = [(NOON - 30 * DAY, {"fee_native": 1.0}), (NOON, {"fee_native": 2.0})]
    assert len(history._prune([{"t": t, **f} for t, f in rows], NOON)) == 1


# ── history: the baseline, and when it refuses to exist ──────────────────────


def test_a_baseline_needs_readings_from_several_days():
    """
    The decisive guard. Samples are taken only while somebody has the page open,
    so fifteen readings from one long afternoon are one observation of one
    afternoon — not a baseline, however many rows it fills.
    """
    _seed("ethereum", [(NOON - 1 * DAY + i * 60, {"fee_native": 0.001}) for i in range(20)])
    assert history.baseline("ethereum", "fee_native", now=NOON) is None


def test_a_baseline_needs_enough_readings():
    _fees("ethereum", days=2, value=0.001)
    assert history.baseline("ethereum", "fee_native", now=NOON) is None


def test_a_warm_baseline_reports_what_it_was_built_from():
    _fees("ethereum", days=6, value=0.001)
    base = history.baseline("ethereum", "fee_native", now=NOON)

    assert base["median"] == pytest.approx(0.001)
    assert base["samples"] == 6
    assert base["days"] == 6


def test_a_reading_is_only_compared_against_its_own_hour_of_day():
    """
    Gas prices are diurnal and so is browsing, and the two correlate. A median
    over the whole window would be drawn mostly from the hours people happen to
    visit, and would flag a perfectly normal quiet hour as an anomaly — a number
    that looks authoritative and is not. Comparing like hours removes the term
    entirely.
    """
    _fees("ethereum", days=6, value=0.001, hour_offset=8)
    assert history.baseline("ethereum", "fee_native", now=NOON) is None


def test_the_hour_band_admits_its_neighbours():
    """An hour either side, or the band never fills at a realistic visit rate."""
    _fees("ethereum", days=6, value=0.001, hour_offset=1)
    assert history.baseline("ethereum", "fee_native", now=NOON) is not None


def test_the_band_wraps_around_midnight():
    midnight = datetime(2026, 8, 18, 0, 0, tzinfo=UTC).timestamp()
    assert history._in_band(23, 0)
    assert history._in_band(1, 0)
    assert not history._in_band(3, 0)
    assert history._hour_of(midnight) == 0


# ── anomaly: fees and load ───────────────────────────────────────────────────


def test_a_fee_spike_must_clear_both_tests():
    """
    Dispersion alone fires constantly on a chain whose fee never moves, because
    MAD collapses to zero there. A plain doubling alone fires on any chain with a
    near-zero base. A spike has to be both unusual and large.
    """
    _seed(
        "ethereum",
        [(NOON - day * DAY, {"fee_native": 0.001 + day * 0.0001}) for day in range(1, 7)],
    )
    row = _row("ethereum", fee={"transfer_native": 0.0016})

    assert anomaly._fee_flag(row, NOON) is None, "60% above a noisy median is not a spike"

    row["fee"]["transfer_native"] = 0.02
    flag = anomaly._fee_flag(row, NOON)
    assert flag and flag["kind"] == "fee"
    assert "hour of day" in flag["text"]


def test_no_baseline_means_no_fee_judgement():
    """A chain nobody has watched yet is unknown, not normal."""
    assert anomaly._fee_flag(_row("bsc", fee={"transfer_native": 99.0}), NOON) is None


# ── anomaly: intra-snapshot readings ─────────────────────────────────────────


def _blocks(*fills: float) -> list[dict]:
    return [{"fill_percent": fill} for fill in fills]


def test_ten_blocks_are_a_trend_on_ethereum():
    row = _row(
        "ethereum",
        cadence_span_seconds=120,
        blocks=_blocks(95, 92, 90, 88, 91, 60, 58, 62, 55, 59),
    )
    flag = anomaly._fill_trend(row)
    assert flag["kind"] == "filling"
    assert "120s" in flag["text"], "The window must ride along with the claim"


def test_ten_blocks_are_not_a_trend_on_a_fast_chain():
    """
    Ten BSC blocks span about four and a half seconds. The difference between
    their halves is jitter, and calling it a trend would be reading noise with a
    chart drawn around it.
    """
    row = _row(
        "bsc", cadence_span_seconds=4.5, blocks=_blocks(95, 92, 90, 88, 91, 60, 58, 62, 55, 59)
    )
    assert anomaly._fill_trend(row) is None


def test_a_full_chain_that_is_not_getting_fuller_is_not_flagged():
    row = _row("ethereum", cadence_span_seconds=120, blocks=_blocks(*([90] * 10)))
    assert anomaly._fill_trend(row) is None


def test_a_dust_queue_is_not_congestion():
    """
    The gap between the raw backlog and the fee-contested one is the signal. A
    large queue nobody is bidding for is the state most often misreported as
    congestion, and the two call for opposite reactions.
    """
    row = _row("bitcoin", mempool={"backlog_blocks": 1, "raw_backlog_blocks": 40})
    flag = anomaly._mempool_flag(row)
    assert flag["kind"] == "dust_queue"
    assert "rather than congestion" in flag["text"]


def test_real_congestion_is_reported_with_its_clearing_price():
    row = _row(
        "bitcoin",
        mempool={
            "backlog_blocks": 6,
            "raw_backlog_blocks": 8,
            "contested_fee_threshold_sat_vb": 14,
        },
    )
    flag = anomaly._mempool_flag(row)
    assert flag["kind"] == "congested"
    assert "14 sat/vB" in flag["text"]


def test_solana_reports_skipped_slots_and_never_a_transaction_count():
    """Solana's `tx_count` is always None; a detector must not trip over that."""
    row = _row("solana", tx_count=None, throughput={"skipped_slot_percent": 7.5}, blocks=[])
    assert anomaly._skipped_slots(row)["kind"] == "skipped_slots"
    assert anomaly._fill_trend(row) is None


def test_tron_reports_nothing_rather_than_zero():
    """Tron has no load ceiling and a fixed zero fee — neither is an anomaly."""
    row = _row("tron", load=None, fee={"transfer_native": 0.0, "is_fixed": True})
    assert anomaly._fee_flag(row, NOON) is None
    assert anomaly._load_flag(row, NOON) is None


# ── anomaly: exchange flows ──────────────────────────────────────────────────


def _daily(count: int, addresses: int, newest: int) -> list[dict]:
    rows = [{"active_addresses": addresses, "transactions": None, "net_flow_usd": None}] * count
    return [*rows, {"active_addresses": newest, "transactions": None, "net_flow_usd": None}]


def test_activity_needs_a_real_baseline_before_it_is_judged():
    """
    Four priors is not a baseline. This is why `flows.LOOKBACK_DAYS` was raised —
    a deviation measured against a handful of days looks authoritative and is not.
    """
    assert anomaly._activity_flags("BTC", _daily(4, 900_000, 1_400_000)) == []


def test_a_large_activity_deviation_is_flagged_with_its_sample_size():
    flags = anomaly._activity_flags("BTC", _daily(20, 900_000, 1_400_000))
    assert flags and flags[0]["severity"] == "high"
    assert "prior 20 days" in flags[0]["basis"]


# ── the detector as a whole ──────────────────────────────────────────────────


def test_an_unreachable_chain_is_named_rather_than_passed_over():
    """
    A chain with no baseline and a chain behaving normally look identical in an
    empty result, and only one of them is reassuring.
    """
    detection = anomaly.detect(_board(_row("base", error="timeout")))
    assert "base" in detection["not_checkable"]
    assert "blank, not idle" in detection["not_checkable"]["base"]
    assert "base" not in detection["checked"]


def test_a_quiet_board_produces_nothing_to_explain():
    detection = anomaly.detect(_board(_row("ethereum", fee={"transfer_native": 0.001})))
    assert detection["anomalies"] == []


async def test_a_quiet_board_never_reaches_the_model(monkeypatch):
    """
    The board refreshes every ten seconds. A quiet board that still cost a
    generation would be the entire cost story of this feature.
    """
    from services import llm

    calls = []

    async def fail(*_args, **_kwargs):
        calls.append(1)
        return "should not happen"

    monkeypatch.setattr(llm, "generate", fail)

    note = await anomaly.anomaly_note(anomaly.detect(_board(_row("ethereum"))))
    assert note["status"] == ai_notes.STATUS_UNAVAILABLE
    assert note["reason"] == ai_notes.REASON_NOTHING_FLAGGED
    assert not calls


def test_only_the_worst_are_shown_and_the_rest_are_counted():
    rows = [
        _row(
            "bitcoin",
            mempool={"backlog_blocks": 9, "raw_backlog_blocks": 10},
            economics={"difficulty_change_percent": 8.0},
        ),
        _row("solana", throughput={"skipped_slot_percent": 9.0}),
        _row("ethereum", cadence_span_seconds=120, blocks=_blocks(95, 93, 92, 90, 55, 52, 50, 51)),
    ]
    detection = anomaly.detect(_board(*rows))

    assert len(detection["anomalies"]) == anomaly.MAX_ANOMALIES
    assert detection["suppressed"] >= 1


def test_the_fingerprint_ignores_how_far_a_flag_has_moved():
    """
    A fee spike lasting an hour is one note, not the three hundred and sixty the
    board's ten-second refresh would otherwise ask for. Severity is in the key
    because a condition getting worse deserves re-describing; a decimal place
    moving does not.
    """
    mild = anomaly.detect(_board(_row("bitcoin", mempool={"backlog_blocks": 4})))
    worse = anomaly.detect(_board(_row("bitcoin", mempool={"backlog_blocks": 7})))
    assert anomaly.note_facts(mild)["flags"] == anomaly.note_facts(worse)["flags"]


def test_the_two_baselines_are_described_separately():
    """
    The first version folded them into one sentence, and the model read "the
    history is still filling" as covering the daily figures too — which are
    thirty days deep and were never the thin half.
    """
    coverage = anomaly.detect(_board(_row("ethereum")))["coverage"]
    assert "none yet" in coverage, "the fee baseline is cold on a fresh install"
    assert "thirty days" in coverage, "the daily history is not, and must not read as if it were"


def test_the_model_only_ever_sees_the_coarse_figures():
    """
    The regression that made this split necessary. `text` moves on every
    ten-second board refresh, so fingerprinting it meant a fresh note every ten
    seconds for a situation that had not changed — and, worse, a cached note
    quoting a backlog that had since moved. The model is handed `phrase`, whose
    figures are snapped to a grain, and never the exact one.
    """
    forty_three = anomaly.detect(
        _board(_row("bitcoin", mempool={"backlog_blocks": 0, "raw_backlog_blocks": 43}))
    )
    forty_five = anomaly.detect(
        _board(_row("bitcoin", mempool={"backlog_blocks": 0, "raw_backlog_blocks": 45}))
    )

    assert forty_three["anomalies"][0]["text"] != forty_five["anomalies"][0]["text"]
    assert anomaly.note_facts(forty_three) == anomaly.note_facts(forty_five)

    supplied = anomaly.note_values(anomaly.note_facts(forty_three))["detected"]
    assert "43" not in supplied and "45" not in supplied


def _placeholders(name: str) -> set:
    import re

    from services.prompts import load_prompt

    return set(re.findall(r"\{\{(\w+)\}\}", load_prompt(name)))


def test_the_prompt_asks_for_exactly_what_the_facts_supply():
    """
    The same contract `test_prompts.py` enforces for literally-named templates,
    checked here because a note names its template through a spec. A placeholder
    nobody fills reaches the model as `{{...}}`; a key no placeholder uses is a
    detected flag quietly dropped before the model ever sees it.
    """
    detection = anomaly.detect(_board(_row("bitcoin", mempool={"backlog_blocks": 6})))
    supplied = set(anomaly.note_values(anomaly.note_facts(detection))) | {"rules"}
    assert _placeholders(anomaly.NOTE_SPEC.prompt) == supplied
