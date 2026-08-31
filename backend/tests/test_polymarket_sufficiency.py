"""
The gate that decides no verdict gets written.

This is the executable form of the product rule that a plausible wrong answer is
worse than an admitted gap. Everything else in the analysis pipeline may degrade
quietly; this may not, because what it guards against is a fluent,
sourced-looking paragraph assembled out of two headlines and a state wire.

The distinction the tests keep circling is sources versus *outlets*. Four
articles from one newsroom are four accounts of one reading, and no number of
them adds up to corroboration.
"""

import pytest

from models.polymarket import EvidenceCoverage, SweepAttempt
from services.polymarket.registry import strategy_for
from services.polymarket.sufficiency import assess, describe_failure

GENERAL = strategy_for("general")
SPORTS = strategy_for("sports")


def coverage(
    *,
    sources=5,
    domains=4,
    tier1=2,
    body=2000,
    answered=3,
    issued=4,
    attempted=(),
) -> EvidenceCoverage:
    """A comfortably sufficient base, overridden one floor at a time."""
    return EvidenceCoverage(
        attempted=list(attempted),
        total_sources=sources,
        distinct_domains=domains,
        tier1_sources=tier1,
        body_chars=body,
        queries_answered=answered,
        queries_issued=issued,
    )


class TestFloors:
    def test_a_full_evidence_base_earns_a_verdict(self):
        assert assess(coverage(), GENERAL).mode == "ok"

    def test_four_articles_from_one_outlet_are_one_source(self):
        """
        The single most important floor. Nothing inside a single newsroom's
        coverage can contradict the rest of it, so it cannot be cross-checked
        however much of it there is.
        """
        verdict = assess(coverage(sources=4, domains=1, body=3000), GENERAL)

        assert verdict.mode == "insufficient"
        assert verdict.reason_code == "single_domain"

    def test_headlines_without_article_text_are_not_an_account(self):
        verdict = assess(coverage(body=200), GENERAL)

        assert verdict.mode != "ok"

    def test_a_thin_but_corroborated_base_is_degraded_not_refused(self):
        """
        Three outlets and a short read is enough to say something with a stated
        ceiling on confidence — but not enough to say it plainly.
        """
        verdict = assess(coverage(sources=3, domains=2, tier1=1, body=700), GENERAL)

        assert verdict.mode == "degraded"
        assert verdict.failures

    def test_nothing_at_all_is_refused_as_no_sources(self):
        verdict = assess(coverage(sources=0, domains=0, tier1=0, body=0, answered=0), GENERAL)

        assert verdict.mode == "insufficient"
        assert verdict.reason_code == "no_sources"


class TestTimeout:
    def test_a_slow_run_that_still_cleared_the_floors_is_a_success(self):
        """
        A timeout is not a separate branch. A sweep that ran out of time having
        already collected five sources across four outlets is a slow success,
        and refusing it would throw away work that met every standard.
        """
        attempts = (SweepAttempt(kind="search", target="q", outcome="timeout"),)

        assert assess(coverage(attempted=attempts), GENERAL).mode == "ok"

    def test_a_timeout_that_left_too_little_is_reported_as_the_cause(self):
        """
        The reader needs to know this is worth retrying, which "thin evidence"
        would not tell them.
        """
        attempts = (SweepAttempt(kind="search", target="q", outcome="timeout"),)
        verdict = assess(
            coverage(sources=2, domains=2, tier1=0, body=100, attempted=attempts),
            GENERAL,
        )

        assert verdict.mode == "insufficient"
        assert verdict.reason_code == "timeout"


class TestCategoryOverrides:
    def test_sport_does_not_require_a_named_desk(self):
        """
        The primary record in sport is a scoreline and a team sheet, not prose.
        Demanding a scraped article from a named desk refuses markets that are
        in fact well covered — so the floor moves rather than disappears.
        """
        thin = coverage(sources=3, domains=3, tier1=0, body=1500)

        assert assess(thin, SPORTS).mode == "ok"
        assert assess(thin, GENERAL).mode == "degraded"


class TestExplanation:
    def test_the_explanation_names_the_searches_that_came_back_empty(self):
        """
        This paragraph is the whole user-facing answer when no verdict exists.
        It has to distinguish an uncovered market from a failed fetch, because
        only one of those is worth retrying.
        """
        attempts = (
            SweepAttempt(kind="search", target="Ukraine ceasefire March", outcome="empty"),
            SweepAttempt(kind="search", target="ceasefire signed", outcome="empty"),
            SweepAttempt(kind="feed", target="Al Jazeera", outcome="timeout"),
        )
        cov = coverage(sources=2, domains=1, tier1=0, body=740, attempted=attempts)
        verdict = assess(cov, GENERAL)

        text = describe_failure(cov, verdict)

        assert "Ukraine ceasefire March" in text
        assert "Al Jazeera" in text
        assert "740" in text
        assert "No verdict was produced" in text

    @pytest.mark.parametrize("total", [0, 3])
    def test_the_explanation_never_raises_on_any_coverage(self, total):
        cov = coverage(sources=total, domains=total, tier1=0, body=total * 10)

        assert describe_failure(cov, assess(cov, GENERAL))
