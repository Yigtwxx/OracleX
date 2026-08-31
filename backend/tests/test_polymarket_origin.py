"""
Why a market was opened — and what the answer is allowed to be when nobody wrote
it down.

This stage is the one place in the prediction-market surface that is permitted to
say something it cannot source. That permission is narrow and every boundary of
it is asserted here:

* the model is asked **even when the search found nothing**, because a category,
  an opening date and a resolution rule are enough to say what kind of thing
  opens a market like this one;
* a hypothesis is deleted the moment a sourced answer exists to displace it;
* a trigger still has to be dated, in-window and on the list it was given, and
  those three checks live in Python where a prompt edit cannot reach them.

The last point is the reason this file is separate from the pipeline suite. The
verdict pipeline's rule is "never speak without evidence"; this stage's rule is
"speak, but label it" — and the only thing keeping the second from eroding the
first is that the conjecture never leaves this module.
"""

import asyncio
from datetime import UTC, datetime

import pytest

from models.polymarket import SharpMove
from services import llm
from services.polymarket import clob, data_api, gamma
from services.polymarket import origin as origin_stage

RAW = {
    "id": "900",
    "slug": "will-the-sec-approve-something",
    "question": "Will the SEC approve something by June 30, 2026?",
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
    "tags": [{"slug": "crypto"}],
}

CREATION = SharpMove(
    kind="creation",
    started_at=gamma._as_datetime("2026-03-01T12:00:00Z"),
    ended_at=gamma._as_datetime("2026-03-03T12:00:00Z"),
)


def _hit(url: str, published_at: str | None) -> dict:
    return {
        "title": "Something happened",
        "snippet": "A thing occurred.",
        "url": url,
        "published_at": published_at,
        "source": "Example",
    }


async def _facts():
    from services.polymarket import facts as facts_stage

    market_facts, _micro = await facts_stage.gather_facts(RAW, include_trades=False)
    return market_facts


@pytest.fixture
def quiet_upstreams(monkeypatch):
    """The market's own endpoints reachable and empty, so only the search varies."""

    async def no_history(token_id, **kwargs):
        return []

    async def no_holders(condition_id, labels, **kwargs):
        return []

    monkeypatch.setattr(clob, "fetch_history", no_history)
    monkeypatch.setattr(data_api, "fetch_holders", no_holders)


@pytest.fixture
def model(monkeypatch):
    """A model whose reply each test sets, and which records that it was asked."""

    class Model:
        def __init__(self):
            self.calls = 0
            self.reply = "{}"
            self.prompts: list[str] = []

        async def generate(self, prompt, **kwargs):
            self.calls += 1
            self.prompts.append(prompt)
            return self.reply

    spy = Model()
    monkeypatch.setattr(llm, "generate", spy.generate)

    async def no_preference(user_id, feature):
        return None

    monkeypatch.setattr(llm, "provider_for", no_preference)
    return spy


def _search(monkeypatch, hits: list[dict]):
    async def search_news(query, **kwargs):
        return list(hits)

    import services.web_search_service as web

    monkeypatch.setattr(web, "search_news", search_news)


def _trace(monkeypatch, model, *, hits: list[dict], reply: str):
    _search(monkeypatch, hits)
    model.reply = reply
    facts = asyncio.run(_facts())
    from services.polymarket.registry import strategy_for

    return asyncio.run(
        origin_stage.trace_origin(facts, "SEC approval", strategy_for(facts.market.category))
    )


class TestTheModelIsAlwaysAsked:
    def test_an_empty_search_still_reaches_the_model(self, quiet_upstreams, model, monkeypatch):
        """
        The change this module exists for.

        The old stage returned `undetermined` without asking anything when no
        dated candidate survived, so a market with an unreadable date field was
        indistinguishable from a market nobody had written about. Neither reader
        got an answer, and only one of them should have been denied one.
        """
        origin, candidates, _attempts = _trace(
            monkeypatch,
            model,
            hits=[],
            reply='{"conjecture": "It may have been opened around an SEC decision window.",'
            ' "conjecture_basis": ["The category resolves on a regulator\'s decision."]}',
        )

        assert model.calls == 1
        assert candidates == {}
        assert origin.status == "conjectured"
        assert origin.conjecture

    def test_the_prompt_carries_the_resolution_criteria(self, quiet_upstreams, model, monkeypatch):
        """
        With no reporting to read, the criteria and the dates are the only facts
        the hypothesis is allowed to rest on. They have to be on the page.
        """
        _trace(monkeypatch, model, hits=[], reply="{}")

        assert "Resolves Yes if it does." in model.prompts[0]
        assert "2026-03-01" in model.prompts[0]


class TestTriggersStayGrounded:
    def test_an_undated_story_is_offered_as_background_not_as_an_s_id(
        self, quiet_upstreams, model, monkeypatch
    ):
        """
        The only thing tying a story to a price move is when it was published, so
        an item of unknown age has no claim on any window. It is still shown to
        the model — under a C id, which no trigger may cite.
        """
        _origin, candidates, _attempts = _trace(
            monkeypatch,
            model,
            hits=[_hit("https://example.com/a", None)],
            reply="{}",
        )

        assert list(candidates) == ["C1"], "background material keeps its own namespace"
        assert candidates["C1"]["in_window"] is False

    def test_a_trigger_citing_background_is_deleted(self, quiet_upstreams, model, monkeypatch):
        """
        The id namespace is a signal, not a guarantee. A local model cited a
        background story anyway on a live Fed market; this is the check that
        caught it.
        """
        origin, _candidates, _attempts = _trace(
            monkeypatch,
            model,
            hits=[_hit("https://example.com/a", None)],
            reply='{"triggers": [{"summary": "A thing happened.", "source_id": "C1"}]}',
        )

        assert origin.triggers == []

    def test_a_story_outside_every_window_cannot_be_a_trigger(
        self, quiet_upstreams, model, monkeypatch
    ):
        origin, _candidates, _attempts = _trace(
            monkeypatch,
            model,
            hits=[_hit("https://example.com/a", "2025-01-01T00:00:00Z")],
            reply='{"triggers": [{"summary": "A thing happened.", "source_id": "C1"}]}',
        )

        assert origin.triggers == []

    def test_a_dated_in_window_story_survives(self, quiet_upstreams, model, monkeypatch):
        origin, _candidates, _attempts = _trace(
            monkeypatch,
            model,
            hits=[_hit("https://example.com/a", "2026-03-02T09:00:00Z")],
            reply='{"triggers": [{"summary": "A thing happened.", "source_id": "S1"}]}',
        )

        assert origin.status == "traced"
        assert [t.source_id for t in origin.triggers] == ["S1"]

    def test_a_trigger_citing_an_unknown_id_is_dropped(self, quiet_upstreams, model, monkeypatch):
        """A cited id that was never offered is a fabrication, not a near miss."""
        origin, _candidates, _attempts = _trace(
            monkeypatch,
            model,
            hits=[_hit("https://example.com/a", "2026-03-02T09:00:00Z")],
            reply='{"triggers": [{"summary": "Invented.", "source_id": "S9"}]}',
        )

        assert origin.triggers == []


class TestTheConjectureIsFenced:
    def test_a_sourced_trigger_displaces_the_conjecture(self, quiet_upstreams, model, monkeypatch):
        """
        Printing a hypothesis beside a sourced answer invites the reader to
        average the two, which is the one reading neither supports.

        The model is asked for the conjecture every time — it cannot know which
        of its triggers will survive the window check — so this gate is the only
        thing that keeps the two apart.
        """
        origin, _candidates, _attempts = _trace(
            monkeypatch,
            model,
            hits=[_hit("https://example.com/a", "2026-03-02T09:00:00Z")],
            reply='{"triggers": [{"summary": "A thing happened.", "source_id": "S1"}],'
            ' "conjecture": "It may have been the SEC.",'
            ' "conjecture_basis": ["A guess."]}',
        )

        assert origin.status == "traced"
        assert origin.conjecture is None
        assert origin.conjecture_basis == []

    def test_a_rationale_also_displaces_the_conjecture(self, quiet_upstreams, model, monkeypatch):
        origin, _candidates, _attempts = _trace(
            monkeypatch,
            model,
            hits=[],
            reply='{"opening_rationale": "It was opened after the filing.",'
            ' "conjecture": "It may have been the SEC."}',
        )

        assert origin.status == "traced"
        assert origin.conjecture is None

    def test_a_deleted_trigger_still_leaves_the_conjecture_standing(
        self, quiet_upstreams, model, monkeypatch
    ):
        """
        The failure this gate was moved into Python for.

        The model named a trigger and, believing it had one, left the conjecture
        null. The trigger cited background material and was deleted, and the
        reader got an empty panel from a run that had something to say. Now the
        conjecture is asked for regardless and survives the deletion.
        """
        origin, _candidates, _attempts = _trace(
            monkeypatch,
            model,
            hits=[_hit("https://example.com/a", None)],
            reply='{"triggers": [{"summary": "A thing happened.", "source_id": "C1"}],'
            ' "conjecture": "It may have been opened around a scheduled decision."}',
        )

        assert origin.triggers == []
        assert origin.status == "conjectured"
        assert origin.conjecture

    def test_nothing_at_all_is_undetermined_rather_than_conjectured(
        self, quiet_upstreams, model, monkeypatch
    ):
        """
        A model that declines to hypothesise is obeying the last rule on the
        prompt, not failing. `undetermined` is the honest rendering of that.
        """
        origin, _candidates, _attempts = _trace(monkeypatch, model, hits=[], reply="{}")

        assert origin.status == "undetermined"
        assert origin.conjecture is None


class TestWhatWasTried:
    def test_an_empty_search_is_still_recorded(self, quiet_upstreams, model, monkeypatch):
        """
        "Nobody wrote about this" and "we could not reach anything" look the same
        to a reader unless the empty queries are named.
        """
        _origin, _candidates, attempts = _trace(monkeypatch, model, hits=[], reply="{}")

        assert attempts, "a stage that lists no attempts explains nothing"
        assert all(a.outcome == "empty" for a in attempts)

    def test_the_opening_window_gets_an_undated_query(self, quiet_upstreams, model, monkeypatch):
        """
        A market opened months ago has no fresh reporting on its opening day, so
        the two date-pinned queries come back empty and the stage would have had
        nothing at all to reason from.
        """
        _origin, _candidates, attempts = _trace(monkeypatch, model, hits=[], reply="{}")

        assert "SEC approval" in {a.target for a in attempts}


class TestReportShape:
    def test_the_report_is_self_contained(self, quiet_upstreams, model, monkeypatch):
        """
        It lands on its own schedule, before or after the verdict, so it carries
        its own identity and its own record rather than borrowing the analysis
        payload's.
        """
        _search(monkeypatch, [_hit("https://example.com/a", "2026-03-02T09:00:00Z")])
        model.reply = '{"triggers": [{"summary": "A thing happened.", "source_id": "S1"}]}'

        report = asyncio.run(origin_stage.build_origin_report(RAW))

        assert report.slug == RAW["slug"]
        assert report.question == RAW["question"]
        assert report.status == "traced"
        assert [s.id for s in report.sources] == ["S1"]
        assert report.sources[0].domain == "example.com"
        assert report.moves, "the windows that were searched travel with the answer"
        assert report.generated_at <= datetime.now(UTC)

    def test_a_disabled_instance_says_so_rather_than_searching(
        self, quiet_upstreams, model, monkeypatch
    ):
        from config import settings

        searched = False

        async def tripwire(query, **kwargs):
            nonlocal searched
            searched = True
            return []

        import services.web_search_service as web

        monkeypatch.setattr(web, "search_news", tripwire)
        monkeypatch.setattr(settings, "USE_AI", False)

        report = asyncio.run(origin_stage.build_origin_report(RAW))

        assert report.status == "undetermined"
        assert model.calls == 0
        assert searched is False
