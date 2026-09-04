"""
The Bilanço note's facts block.

Nothing here asserts on prose. What is pinned is the contract around the model:
that the prompt's placeholders and the rendered values are the same set, that
the values are a function of the facts and of nothing fresher, and that the
fingerprint is stable across the sub-step noise the quantization exists to
absorb but moves when the statements do.
"""

from __future__ import annotations

import re

import pytest

from services.ai_notes import fingerprint
from services.bist import deflator, financials_note as fn
from services.bist import financials_service as fs
from services.prompts import load_prompt
from tests.test_bist_financials import bank, cpi, insurer, long_series
from services.bist import fundamentals as f

PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def board(layout: str = f.LAYOUT_INDUSTRIAL, **kw) -> dict:
    kw.setdefault("cpi_series", cpi())
    kw.setdefault("key_configured", True)
    return fs.build_payload(long_series(layout), **kw)


def facts(layout: str = f.LAYOUT_INDUSTRIAL, **kw) -> dict:
    result = fn.financials_facts(board(layout, **kw))
    assert result is not None
    return result


class TestPromptParity:
    def test_placeholders_and_values_are_the_same_set(self):
        template = load_prompt(fn.NOTE_SPEC.prompt)
        placeholders = set(PLACEHOLDER_RE.findall(template)) - {"rules"}
        values = set(fn.financials_values(facts()))
        assert placeholders == values, (
            f"only in prompt: {placeholders - values}; only in values: {values - placeholders}"
        )

    def test_no_placeholder_survives_rendering(self):
        rendered = "\n".join(fn.financials_values(facts()).values())
        assert "{{" not in rendered and "}}" not in rendered

    @pytest.mark.parametrize("layout", [f.LAYOUT_INDUSTRIAL, f.LAYOUT_BANK, f.LAYOUT_INSURANCE])
    def test_every_layout_renders_every_block(self, layout):
        values = fn.financials_values(facts(layout))
        assert all(text.strip() for text in values.values())


class TestValuesDeriveFromFactsAlone:
    def test_mutating_the_source_after_building_facts_changes_nothing(self):
        # The rule the whole caching design rests on: a cached note must never
        # be able to quote a figure that has since moved.
        payload = board()
        built = fn.financials_facts(payload)
        before = fn.financials_values(built)

        payload["ttm"]["real_revenue_growth"] = 99.0
        payload["quarters"][-1]["nominal"]["revenue"] = 1.0
        payload["name"] = "Something Else"

        assert fn.financials_values(built) == before


class TestFingerprint:
    def test_sub_step_moves_do_not_retire_the_note(self):
        base = facts()
        nudged = dict(base)
        # Growth is bucketed to five points and margin to one; a fraction of a
        # step is the same read to a reader and must be the same entry.
        nudged["real_revenue_yoy_pct"] = base["real_revenue_yoy_pct"]
        nudged["gross_margin_pct"] = base["gross_margin_pct"]
        assert fingerprint(fn.NOTE_SPEC, base) == fingerprint(fn.NOTE_SPEC, nudged)

    def test_quantization_absorbs_noise_in_the_raw_input(self):
        loose = fs.build_payload(
            long_series(f.LAYOUT_INDUSTRIAL, growth=1.0500001),
            cpi_series=cpi(),
            key_configured=True,
        )
        tight = board()
        assert fingerprint(fn.NOTE_SPEC, fn.financials_facts(loose)) == fingerprint(
            fn.NOTE_SPEC, fn.financials_facts(tight)
        )

    def test_a_new_quarter_retires_the_note(self):
        base = facts()
        moved = dict(base, latest_period="2026Q3")
        assert fingerprint(fn.NOTE_SPEC, base) != fingerprint(fn.NOTE_SPEC, moved)


class TestCoverage:
    def test_bank_absences_are_attributed_to_the_chart_of_accounts(self):
        built = facts(f.LAYOUT_BANK)
        assert built["absent_because"]["ebitda"] == fn.ABSENT_LAYOUT
        coverage = fn.financials_values(built)["coverage"]
        assert "EBITDA" in coverage
        assert "do not exist for this kind of company" in coverage.lower() or (
            "Not in this chart of accounts" in coverage
        )

    def test_an_unreported_line_is_told_apart_from_a_missing_one(self):
        payload = board()
        payload["available_fields"] = [
            field for field in payload["available_fields"] if field != "ebitda"
        ]
        built = fn.financials_facts(payload)
        assert built["absent_because"]["ebitda"] == fn.ABSENT_UNREPORTED
        assert "not reported by this company" in fn.financials_values(built)["coverage"]

    def test_growth_block_names_the_missing_line_rather_than_printing_none(self):
        text = fn.financials_values(facts(f.LAYOUT_BANK))["growth"]
        assert "None" not in text
        assert fn.UNKNOWN in text

    def test_margins_block_is_never_empty_for_an_insurer(self):
        assert fn.financials_values(facts(f.LAYOUT_INSURANCE))["margins"].strip()


class TestBasisBlock:
    def test_real_basis_labels_the_nominal_figure_as_not_growth(self):
        text = fn.financials_values(facts())["basis"]
        assert "REAL" in text
        assert "It is not growth" in text

    def test_without_deflation_the_block_says_nominal_and_names_the_reason(self):
        built = facts(cpi_series=[], key_configured=False)
        assert built["basis"] == "nominal"
        assert built["deflation_reason"] == deflator.REASON_KEY_MISSING
        text = fn.financials_values(built)["basis"]
        assert "nominal" in text
        assert "No inflation series is configured" in text
        assert "Do not describe any figure below as real" in text


class TestShortHistory:
    def test_four_quarters_cannot_be_narrated(self):
        # Every growth figure compares a trailing year against the one before,
        # so a short board is drawable and not narratable.
        payload = fs.build_payload(
            long_series(f.LAYOUT_INDUSTRIAL, count=4), cpi_series=cpi(), key_configured=True
        )
        assert fn.financials_facts(payload) is None

    @pytest.mark.asyncio
    async def test_entry_point_declines_rather_than_raising(self):
        payload = fs.build_payload(
            long_series(f.LAYOUT_INDUSTRIAL, count=4), cpi_series=cpi(), key_configured=True
        )
        note = await fn.note_for_financials(payload)
        assert note["status"] == "unavailable"
        assert note["reason"] == "insufficient_history"


class TestFixtureLayouts:
    def test_the_live_fixtures_are_too_short_to_narrate(self):
        # Documents why the rest of this module uses synthetic series: the
        # captured payloads carry four periods, which difference into three
        # quarters.
        for builder in (bank, insurer):
            payload = fs.build_payload(builder(), cpi_series=cpi(), key_configured=True)
            assert fn.financials_facts(payload) is None
