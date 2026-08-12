"""
The precedent block a news prompt carries has to state the contradiction.

This is the output the whole retrieval change exists to produce: not a list of
old headlines, but "this resembles X, here is what the price actually did, and
here is whether that matched what the headline implied". A model handed only the
first form reads "SEC sues Ripple" and reasons lawsuit-therefore-down.

`render_precedent_analogies` is the last step before the text reaches the model,
so the sentence being present when the outcome contradicted the headline — and
absent when it did not — is worth pinning down.
"""

from services.rag_v3_service import render_precedent_analogies

CONTRADICTED = {
    "title": "SEC sues Ripple over unregistered XRP sales",
    "date": "2020-12-22",
    "symbol": "XRP",
    "similarity": 0.42,
    "apparent_sentiment": "bearish",
    "durable_direction": "bullish",
    "surprised": True,
    "inverted": True,
    "horizons": {1: -49.4, 7: -57.0, 90: 5.7, 365: 85.4},
    "max_drawdown_pct": -66.1,
    "max_runup_pct": 282.3,
}

CONSISTENT = {
    "title": "Terra UST depegs and LUNA collapses",
    "date": "2022-05-09",
    "symbol": "BTC",
    "similarity": 0.38,
    "apparent_sentiment": "bearish",
    "durable_direction": "bearish",
    "surprised": False,
    "inverted": False,
    "horizons": {1: -8.9, 365: -18.9},
    "max_drawdown_pct": -54.6,
    "max_runup_pct": 2.1,
}

DIVERGED = {
    "title": "Ethereum completes the Merge to proof of stake",
    "date": "2022-09-15",
    "symbol": "ETH",
    "similarity": 0.51,
    "apparent_sentiment": "bullish",
    "durable_direction": "neutral",
    "surprised": False,
    "inverted": True,
    "horizons": {1: -12.5, 365: 0.1},
}


class TestContradictionIsStated:
    def test_a_contradicted_precedent_says_so(self):
        text = render_precedent_analogies([CONTRADICTED])
        assert "the market did the opposite of what the headline implied" in text
        assert "durable outcome was bullish" in text

    def test_a_consistent_precedent_does_not(self):
        text = render_precedent_analogies([CONSISTENT])
        assert "opposite of what the headline implied" not in text

    def test_diverging_horizons_get_the_weaker_note(self):
        text = render_precedent_analogies([DIVERGED])
        assert "immediate reaction and the durable outcome diverged" in text
        assert "opposite of what the headline implied" not in text


class TestWhatTheBlockCarries:
    def test_every_measured_horizon_reaches_the_prompt(self):
        text = render_precedent_analogies([CONTRADICTED])
        for fragment in ("1d -49.4%", "7d -57.0%", "90d +5.7%", "365d +85.4%"):
            assert fragment in text

    def test_the_path_is_reported_alongside_the_endpoints(self):
        # The endpoints alone hide that XRP lost two thirds of its value first.
        text = render_precedent_analogies([CONTRADICTED])
        assert "worst drawdown -66.1%" in text
        assert "best run-up +282.3%" in text

    def test_the_headline_direction_is_stated_as_such(self):
        text = render_precedent_analogies([CONTRADICTED])
        assert "Headline implied BEARISH" in text

    def test_the_block_is_framed_as_history_not_forecast(self):
        text = render_precedent_analogies([CONTRADICTED])
        assert "not projections" in text

    def test_match_strength_is_shown(self):
        assert "match 42%" in render_precedent_analogies([CONTRADICTED])


class TestEmptyAndMalformed:
    def test_no_precedents_renders_nothing(self):
        # An empty string is what the prompt template treats as "no precedent",
        # which is the honest answer and better than an empty header.
        assert render_precedent_analogies([]) == ""

    def test_entries_without_a_title_are_skipped(self):
        assert render_precedent_analogies([{"similarity": 0.9}]) == ""

    def test_an_unmeasured_precedent_still_renders(self):
        text = render_precedent_analogies(
            [{"title": "Some event", "date": "2026-06-01", "similarity": 0.3}]
        )
        assert "Some event" in text
        assert "Actual:" not in text

    def test_the_limit_is_respected(self):
        text = render_precedent_analogies([CONTRADICTED, CONSISTENT, DIVERGED], limit=2)
        assert CONTRADICTED["title"] in text
        assert DIVERGED["title"] not in text
