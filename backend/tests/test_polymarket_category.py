"""
What a market is about, and why that is decided without a model.

The category picks which wires the evidence sweep reads, so it sits upstream of
everything a verdict rests on. A wrong category is not a cosmetic mislabel — it
is a clean, confident run over the wrong newspapers, and nothing downstream can
detect it. These tests pin the two rules that keep it honest: a curated tag is
believed, and a keyword verdict has to be both strong and unambiguous.
"""

from services.polymarket.category import (
    MIN_KEYWORD_SCORE,
    infer_category,
    market_subject,
)


class TestTags:
    def test_a_curated_tag_settles_the_category(self):
        verdict = infer_category("Will anything happen?", tags=("politics",))

        assert verdict.category == "politics"
        assert verdict.matched_on == ("tag:politics",)

    def test_geopolitics_outranks_politics_when_a_market_carries_both(self):
        """
        Nearly every war market is also tagged "politics". Reading one off the
        desks that cover primaries would answer a question about an invasion
        with campaign coverage.
        """
        verdict = infer_category(
            "Will there be a NATO-Russia clash?", tags=("politics", "geopolitics")
        )

        assert verdict.category == "geopolitics"

    def test_market_mechanics_tags_decide_nothing(self):
        """
        Gamma publishes 232 tags and most are plumbing — "recurring",
        "hit-price", "earn-4". An allowlist is the only workable shape.
        """
        verdict = infer_category("Will the price go up?", tags=("recurring", "earn-4"))

        assert verdict.category == "general"


class TestKeywords:
    def test_one_decisive_word_is_enough(self):
        """
        Real market questions are short: "Will Bitcoin reach $150,000?" carries
        exactly one classifying word and it is conclusive. A floor demanding two
        hits sent most real markets to the broad wires.
        """
        verdict = infer_category("Will Bitcoin reach $150,000 by the end of 2026?")

        assert verdict.category == "crypto"

    def test_a_merely_suggestive_word_is_not(self):
        """`vote` is weighted below the floor precisely so it cannot decide."""
        verdict = infer_category("Will the board vote on the merger?")

        assert verdict.category == "general"

    def test_a_tie_between_two_subjects_is_not_a_decision(self):
        """
        "Fed" and "election" score alike here. Without the margin rule the
        answer would be whichever category happened to be declared first, which
        is a coin flip wearing a category's name.
        """
        verdict = infer_category("Will the Fed cut rates before the 2028 election?")

        assert verdict.category == "general"

    def test_a_word_inside_another_word_does_not_count(self):
        """
        Substring matching put "war" inside "Warner" and researched a media
        acquisition off the wires that cover invasions. Terms match as words.
        """
        verdict = infer_category("Will Warner Bros Discovery be acquired in 2026?")

        assert verdict.category == "general"

    def test_the_floor_is_the_weight_of_a_single_decisive_term(self):
        """Guards the relationship the comment in the module claims."""
        assert MIN_KEYWORD_SCORE == 2.0


class TestSubject:
    def test_the_interrogative_is_stripped(self):
        """
        "Will X happen" pasted into a search box matches the word "will" across
        the entire web. The subject has to read like something a person types.
        """
        assert market_subject("Will Bitcoin reach $150,000?") == "Bitcoin reach $150,000"

    def test_a_deadline_clause_is_stripped(self):
        """
        The date is carried separately. Left in the query it pins the search to
        coverage that repeats the deadline rather than coverage that explains
        the event.
        """
        subject = market_subject("Will China invade Taiwan by end of 2026?")

        assert "2026" not in subject
        assert subject == "China invade Taiwan"

    def test_the_expletive_after_the_interrogative_goes_too(self):
        """
        "Will there be X" loses its "Will" and is left starting "there be X",
        which is not a phrase anybody has written. Measured on a live Fed market:
        the query built from it returned six results, none about the meeting.
        """
        subject = market_subject(
            "Will there be no change in Fed interest rates after the September 2026 meeting?"
        )

        assert subject.startswith("no change in Fed interest rates")
        assert "there be" not in subject

    def test_an_unparseable_question_survives_intact(self):
        """
        Over-trimming finds the wrong topic; a slightly wordy query still finds
        the story. When no pattern matches, nothing is removed.
        """
        assert market_subject("Next Mythos-Class Model released") == (
            "Next Mythos-Class Model released"
        )

    def test_an_empty_question_does_not_raise(self):
        assert market_subject("") == ""
