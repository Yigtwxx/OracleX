"""
Deleting anything the evidence does not carry.

The synthesis stage returns claims as objects with source ids rather than prose,
and this is the pass that makes that structure mean something. A model given
eight sources will cite a ninth; a model asked about a market will state a
figure the facts do not contain. Neither is caught by reading the output — both
are caught by lookup, which is why the check lives here and not in a prompt.

The last test in TestSurvivalFloor is the one with teeth: a verdict standing on
a single corroborated claim is not a thin verdict, it is not a verdict, and
showing it as one is the failure this whole surface exists to avoid.
"""

from models.polymarket import Claim, SourceRef
from services.polymarket.attribution import (
    MIN_KEPT_CLAIMS,
    EvidenceLedger,
    drop_unsourced_sentences,
    enforce_attribution,
    verify_market_claim,
)

FACTS = "Leading outcome: Yes at 0.62. Volume: $1,200,000. Spread: 0.03. Drift 7d: 0.11."


def ledger(n: int = 3) -> EvidenceLedger:
    led = EvidenceLedger()
    for i in range(1, n + 1):
        led.add(
            SourceRef(
                id=f"S{i}",
                url=f"https://example{i}.com/a",
                domain=f"example{i}.com",
                title=f"Story {i}",
                tier=1,
                body_chars=900,
            )
        )
    return led


def claim(text: str, sources: list[str]) -> Claim:
    return Claim(text=text, sources=sources)


class TestInventedSources:
    def test_a_claim_citing_a_source_we_do_not_hold_is_deleted(self):
        """
        A model handed eight sources cites S12. The id space is known exactly,
        so this is a lookup rather than a judgement.
        """
        kept, report = enforce_attribution(
            [claim("Something happened.", ["S12"])], ledger(3), FACTS
        )

        assert kept == []
        assert report.claims_kept == 0
        assert "S12" in report.dropped[0]

    def test_a_claim_keeps_only_the_ids_that_resolve(self):
        kept, _ = enforce_attribution(
            [claim("Something happened.", ["S1", "S99"])], ledger(3), FACTS
        )

        assert kept[0].sources == ["S1"]

    def test_a_claim_with_no_source_at_all_is_deleted(self):
        kept, report = enforce_attribution([claim("Trust me.", [])], ledger(3), FACTS)

        assert kept == []
        assert "carried no source" in report.dropped[0]

    def test_what_was_deleted_is_reported_rather_than_silently_dropped(self):
        """The pruning is shown to the reader; silence would look like agreement."""
        _, report = enforce_attribution(
            [claim("A.", ["S1"]), claim("B.", ["S9"])], ledger(2), FACTS
        )

        assert report.claims_in == 2
        assert report.claims_kept == 1
        assert len(report.dropped) == 1


class TestMarketSentinel:
    def test_a_claim_about_the_price_may_cite_the_market(self):
        """
        "The market has moved" is true and has no URL. Without the sentinel the
        model must either drop it or invent a link.
        """
        kept, _ = enforce_attribution(
            [claim("The leading outcome sits at 0.62.", ["MARKET"])], ledger(), FACTS
        )

        assert kept[0].sources == ["MARKET"]

    def test_the_sentinel_is_verified_rather_than_trusted(self):
        """
        Otherwise it is a hole big enough to drive any unsourced number through:
        every figure in the claim has to appear in the facts block.
        """
        kept, report = enforce_attribution(
            [claim("Volume has reached $9,400,000.", ["MARKET"])], ledger(), FACTS
        )

        assert kept == []
        assert "the facts do not contain" in report.dropped[0]

    def test_a_qualitative_reading_of_the_book_needs_no_figure(self):
        """
        The check exists to stop invented quantities, not to ban statements
        about the order book that carry no number to check.
        """
        assert verify_market_claim("The market is thinly traded.", FACTS) is True

    def test_figures_match_across_formatting(self):
        """ "$1,200,000" in a claim and 1200000 in the facts are one number."""
        assert verify_market_claim("Volume is 1200000.", FACTS) is True


class TestBottomLine:
    def test_a_sentence_with_no_marker_is_removed(self):
        """
        A summary is where an unsupported sentence hides most comfortably, so
        the rule here is blunt: cite or be deleted.
        """
        text, removed = drop_unsourced_sentences(
            "Rates will fall [S1]. Everyone knows this.", ledger()
        )

        assert text == "Rates will fall."
        assert removed == 1

    def test_markers_do_not_survive_into_the_reader_s_text(self):
        """They are scaffolding for this check, not something to render."""
        text, _ = drop_unsourced_sentences("A holds [S1, S2].", ledger())

        assert "[" not in text

    def test_a_marker_naming_an_unknown_source_does_not_save_a_sentence(self):
        text, removed = drop_unsourced_sentences("Invented support [S42].", ledger(3))

        assert text == ""
        assert removed == 1

    def test_the_summary_is_capped(self):
        sentences = " ".join(f"Point {i} [S1]." for i in range(6))

        text, removed = drop_unsourced_sentences(sentences, ledger())

        assert text.count(".") == 3
        assert removed == 3


class TestSurvivalFloor:
    def test_a_verdict_standing_on_one_claim_is_not_a_verdict(self):
        """
        Callers must treat this as a failed synthesis, not a thin one. The
        constant is asserted here because the pipeline branches on it.
        """
        kept, _ = enforce_attribution(
            [claim("A.", ["S1"]), claim("B.", ["S9"]), claim("C.", [])],
            ledger(2),
            FACTS,
        )

        assert len(kept) < MIN_KEPT_CLAIMS


class TestPunctuation:
    def test_punctuation_is_not_doubled_where_a_marker_was_cut(self):
        """
        Observed in a live run: the model wrote "…direct engagement, [S1]." and
        the summary came back ending ",." — the sort of seam that makes prose
        read as machine-assembled.
        """
        text, _ = drop_unsourced_sentences("Talks stalled, [S1].", ledger())

        assert text == "Talks stalled."
