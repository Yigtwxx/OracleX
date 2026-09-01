"""
The fund allocation grouping.

Fifty-four TEFAS instrument codes collapse into twelve buckets, and the whole
table is written by hand — so the first two tests are about the table itself
rather than about any behaviour. A code that fell out of it would not raise; it
would quietly land in "Diğer" and a fund's bar would stop meaning what it says.

The rest pin the two judgement calls that are easiest to "tidy up" into being
wrong — gold accounts are gold, real-estate fund units are real estate — and the
two refusals: an unreported fund is None rather than an empty bar, and the total
is what TEFAS said rather than a comfortable 100.

Pure arithmetic. Nothing here touches the network or the cache.
"""

from datetime import date

import pytest

from services.bist.fund_allocation import (
    BUCKET_LABELS,
    BUCKET_ORDER,
    FIELD_BUCKETS,
    UNKNOWN_BUCKET,
    bucket_vocabulary,
    bucket_weights,
    group_allocation,
)
from services.bist.tefas_client import ALLOCATION_FIELDS

DAY = date(2026, 8, 28)


def _group(weights: dict[str, float]):
    return group_allocation(weights, DAY)


class TestTable:
    def test_every_tefas_field_has_a_bucket(self):
        assert set(FIELD_BUCKETS) == set(ALLOCATION_FIELDS)

    def test_every_bucket_is_ordered_and_labelled(self):
        assert set(FIELD_BUCKETS.values()) <= set(BUCKET_ORDER)
        assert set(BUCKET_ORDER) == set(BUCKET_LABELS)
        assert len(BUCKET_ORDER) == len(set(BUCKET_ORDER))

    def test_vocabulary_follows_bar_order(self):
        assert [entry["key"] for entry in bucket_vocabulary()] == list(BUCKET_ORDER)


class TestGrouping:
    def test_sums_lines_into_their_bucket(self):
        breakdown = _group({"ost": 0.21, "fb": 0.094, "hs": 0.5})
        weights = bucket_weights(breakdown)
        assert weights["ozel_borclanma"] == pytest.approx(0.304)
        assert weights["hisse"] == 0.5

    def test_lines_are_kept_largest_first(self):
        breakdown = _group({"fb": 0.094, "ost": 0.21})
        bucket = next(b for b in breakdown.buckets if b.key == "ozel_borclanma")
        assert [line.code for line in bucket.lines] == ["ost", "fb"]

    def test_bucket_order_is_fixed_not_input_order(self):
        # Two funds have to be readable against each other, which only works if
        # the same asset class is always at the same position in the bar.
        forwards = _group({"hs": 0.6, "vmtl": 0.4})
        backwards = _group({"vmtl": 0.4, "hs": 0.6})
        assert [b.key for b in forwards.buckets] == [b.key for b in backwards.buckets]
        assert [b.key for b in forwards.buckets] == ["hisse", "mevduat"]

    def test_empty_buckets_are_dropped(self):
        breakdown = _group({"hs": 1.0})
        assert [b.key for b in breakdown.buckets] == ["hisse"]

    def test_zero_and_negative_weights_are_dropped(self):
        breakdown = _group({"hs": 0.6, "km": 0.0, "tr": -0.1})
        assert set(bucket_weights(breakdown)) == {"hisse"}


class TestJudgementCalls:
    def test_gold_accounts_are_metal_not_deposit(self):
        # A katılım gold fund holds almost nothing but `khau`. Filed under
        # deposits it would draw as a money-market fund, which is the single
        # most misleading outcome this grouping can produce.
        assert FIELD_BUCKETS["khau"] == "kiymetli_maden"
        assert FIELD_BUCKETS["vmau"] == "kiymetli_maden"

    def test_property_fund_units_are_property_not_fund_units(self):
        assert FIELD_BUCKETS["gykb"] == "gayrimenkul"
        assert FIELD_BUCKETS["gsykb"] == "gayrimenkul"

    def test_plain_fund_units_stay_fund_units(self):
        # The wrapper really is all we know here, so the wrapper is the label.
        assert FIELD_BUCKETS["yyf"] == "fon"
        assert FIELD_BUCKETS["byf"] == "fon"


class TestRefusals:
    def test_nothing_reported_is_none_not_an_empty_bar(self):
        assert _group({}) is None

    def test_only_zeroes_is_none_too(self):
        assert _group({"hs": 0.0}) is None

    def test_total_is_not_normalised(self):
        breakdown = _group({"hs": 0.5, "vmtl": 0.497})
        assert breakdown.total == pytest.approx(0.997)

    def test_unknown_field_is_kept_under_diger(self):
        # TEFAS added codes in the 2026 rewrite and will again. Dropping one
        # would shrink the bar and leave the shortfall unexplained.
        breakdown = _group({"hs": 0.6, "zzz": 0.4})
        weights = bucket_weights(breakdown)
        assert weights[UNKNOWN_BUCKET] == pytest.approx(0.4)
        assert breakdown.total == pytest.approx(1.0)

    def test_unknown_field_keeps_its_code_as_a_label(self):
        breakdown = _group({"zzz": 0.4})
        line = breakdown.buckets[0].lines[0]
        assert line.code == "zzz"
        assert line.label == "zzz"


def test_real_fund_reproduces_tefas():
    # DFI on 28.08.2026, straight off the endpoint: 53.23 equity, 32 fund
    # units, 14.51 lira deposits, 0.26 corporate paper.
    breakdown = _group({"hs": 0.5323, "yyf": 0.32, "vmtl": 0.1451, "fb": 0.0026})
    assert [b.key for b in breakdown.buckets] == [
        "hisse",
        "fon",
        "ozel_borclanma",
        "mevduat",
    ]
    assert breakdown.total == pytest.approx(1.0)
    assert breakdown.day == DAY
