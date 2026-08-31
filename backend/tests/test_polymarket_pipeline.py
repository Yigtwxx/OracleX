"""
What happens when there is nothing to go on.

This file exists for one assertion, in `test_a_market_with_no_coverage_never_
reaches_the_model`: when the evidence sweep comes back empty, `llm.generate` is
never awaited. Everything else here supports it.

That is the executable form of the product rule. A model handed two headlines
will write a fluent, confident-sounding paragraph, and a reader has no way to
tell that paragraph from one built on real reporting. The only reliable defence
is not to ask — so the gate is in Python, before the call, and this test is what
stops someone removing it later without noticing.

The other half of the rule is that a refusal is not an error. The facts, the
microstructure and the move timeline are computed without a model and are still
served, so declining to judge a market does not blank the page.
"""

import asyncio

import pytest

from services import llm
from services.polymarket import analysis, clob, data_api, feeds
from services.polymarket import evidence as evidence_stage

RAW = {
    "id": "900",
    "slug": "will-something-obscure-happen",
    "question": "Will something extremely obscure happen by June 30, 2026?",
    "description": "Resolves Yes if it does.",
    "outcomes": '["Yes", "No"]',
    "outcomePrices": '["0.31", "0.69"]',
    "clobTokenIds": '["111", "222"]',
    "conditionId": "0xabc",
    "volumeNum": 12_000.0,
    "liquidityNum": 3_000.0,
    "spread": 0.04,
    "endDate": "2026-06-30T00:00:00Z",
    "createdAt": "2026-03-01T12:00:00Z",
    "closed": False,
    "tags": [{"slug": "politics"}],
}


class ModelSpy:
    """Records every call. Raises if one arrives, so a leak is loud."""

    def __init__(self):
        self.calls = 0

    async def generate(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("llm.generate was called with no evidence to reason from")


@pytest.fixture
def silent_web(monkeypatch):
    """Every outside source reachable, and every one of them empty."""
    issued: list[str] = []

    async def no_news(query, **kwargs):
        issued.append(query)
        return []

    async def no_web(query, **kwargs):
        issued.append(query)
        return []

    async def no_feed(url, **kwargs):
        return []

    async def no_history(token_id, **kwargs):
        return []

    async def no_holders(condition_id, labels, **kwargs):
        return []

    import services.web_search_service as web

    monkeypatch.setattr(web, "search_news", no_news)
    monkeypatch.setattr(web, "search_web", no_web)
    monkeypatch.setattr(feeds, "fetch_feed", no_feed)
    monkeypatch.setattr(clob, "fetch_history", no_history)
    monkeypatch.setattr(data_api, "fetch_holders", no_holders)
    return issued


@pytest.fixture
def spy(monkeypatch):
    model = ModelSpy()
    monkeypatch.setattr(llm, "generate", model.generate)

    async def no_preference(user_id, feature):
        return None

    monkeypatch.setattr(llm, "provider_for", no_preference)
    return model


class TestRefusal:
    def test_a_market_with_no_coverage_never_reaches_the_model(self, silent_web, spy):
        """
        The assertion this whole file is for.

        A model asked to judge a market on nothing produces prose that reads
        exactly like a judgement made on something.
        """
        result = asyncio.run(analysis.analyse_market(RAW))

        assert spy.calls == 0
        assert result.status == "insufficient_evidence"
        assert result.reason_code == "no_sources"

    def test_the_refusal_names_the_searches_that_were_run(self, silent_web, spy):
        """
        "Nobody is covering this" and "we could not reach anything" call for
        different responses, and only one of them is worth retrying.
        """
        result = asyncio.run(analysis.analyse_market(RAW))

        targets = {a.target for a in result.coverage.attempted}
        assert targets, "a refusal that lists no attempts explains nothing"
        # Every query the sweep issued is named. The origin stage's windowed
        # searches are deliberately not counted here: those ask when the price
        # moved, not what is known about the question, and folding them into
        # this total would inflate the effort the reader is told about.
        assert targets & set(silent_web)
        assert "Ran" in result.explanation
        assert "No verdict was produced" in result.explanation

    def test_the_market_facts_survive_a_refusal(self, silent_web, spy):
        """
        Withholding the odds alongside the verdict would turn "we could not
        judge this" into "this market is broken" — a different, false claim.
        """
        result = asyncio.run(analysis.analyse_market(RAW))

        assert result.facts is not None
        assert result.facts.market.question == RAW["question"]
        assert result.microstructure is not None
        assert result.microstructure.leading_outcome == "No"

    def test_the_verdict_carries_no_origin_of_its_own(self, silent_web, spy):
        """
        "Why was this opened" runs as its own job and may end in a labelled
        hypothesis. A hypothesis that reached this payload would be one prompt
        edit away from the synthesis stage, where nothing downstream could tell
        it from evidence.
        """
        result = asyncio.run(analysis.analyse_market(RAW))

        assert not hasattr(result, "origin")


class TestAiDisabled:
    def test_a_disabled_instance_says_so_rather_than_searching(self, monkeypatch, spy):
        """No point spending a sweep budget on a verdict that cannot be written."""
        from config import settings

        monkeypatch.setattr(settings, "USE_AI", False)

        searched = False

        async def tripwire(*args, **kwargs):
            nonlocal searched
            searched = True
            return []

        async def empty(*args, **kwargs):
            return []

        import services.web_search_service as web

        monkeypatch.setattr(web, "search_news", tripwire)
        monkeypatch.setattr(web, "search_web", tripwire)
        # The market's own upstreams are not tripwired: facts are gathered
        # before the AI check on purpose, so that even a refusal carries the
        # odds. What must not happen is the *research* — the web sweep is the
        # expensive half and it buys nothing when no verdict can be written.
        monkeypatch.setattr(clob, "fetch_history", empty)
        monkeypatch.setattr(data_api, "fetch_holders", empty)

        result = asyncio.run(analysis.analyse_market(RAW))

        assert result.status == "insufficient_evidence"
        assert result.reason_code == "ai_disabled"
        assert spy.calls == 0
        assert searched is False
        assert result.facts is not None, "the odds survive an AI outage"


class TestEvidenceCounting:
    def test_a_query_that_returned_nothing_is_still_recorded(self):
        """
        Silence about a failed query makes "uncovered" and "unreachable" look
        the same in the refusal, which is the one thing it has to distinguish.
        """
        sweep = evidence_stage.Sweep(analysis.strategy_for("general"))
        sweep.record("search", "a query", "empty")

        _ledger, coverage = sweep.finish()

        assert coverage.queries_issued == 1
        assert coverage.queries_answered == 0
        assert coverage.attempted[0].target == "a query"

    def test_two_articles_from_one_outlet_count_as_one_domain(self):
        sweep = evidence_stage.Sweep(analysis.strategy_for("general"))
        sweep._absorb(
            [
                {"url": "https://reuters.com/a", "title": "A", "snippet": "x"},
                {"url": "https://reuters.com/b", "title": "B", "snippet": "y"},
            ],
            "search",
        )

        _ledger, coverage = sweep.finish()

        assert coverage.total_sources == 2
        assert coverage.distinct_domains == 1
