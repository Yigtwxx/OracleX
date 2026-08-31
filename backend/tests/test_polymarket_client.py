"""
Reading Polymarket without misreading it.

Two upstream habits are worth pinning down in tests, because both fail quietly
rather than loudly.

The first is that Gamma JSON-encodes its array fields. `outcomes` arrives as the
*string* `'["Yes", "No"]'`, so indexing it yields the character `[`. Nothing
raises; the board simply fills with plausible nonsense. This is the single most
likely way the integration breaks after an upstream change.

The second is that a figure nobody published must stay None. A market with no
holder table and a market whose holder table failed to load render identically
if the gap is filled with zero, and only one of those is a fact about the market.
"""

import asyncio

import pytest

from models.polymarket import Holder, MarketFacts, MarketSummary, Outcome, PricePoint
from services.polymarket import data_api, gamma, microstructure, service

RAW = {
    "id": "512",
    "slug": "will-x-happen",
    "question": "Will X happen by June 30, 2026?",
    "description": "Resolves Yes if X.",
    "outcomes": '["Yes", "No"]',
    "outcomePrices": '["0.62", "0.38"]',
    "clobTokenIds": '["111", "222"]',
    "conditionId": "0xabc",
    "volumeNum": 1_200_000.0,
    "liquidityNum": 48_000.0,
    "spread": 0.03,
    "endDate": "2026-06-30T00:00:00Z",
    "createdAt": "2026-03-01T12:00:00Z",
    "closed": False,
    "tags": [{"slug": "politics"}],
}


class TestGammaParsing:
    def test_json_encoded_arrays_become_real_lists(self):
        """
        `market["outcomePrices"][0]` on the raw payload is the character "[".
        Everything crossing this boundary goes through the coercion.
        """
        parsed = gamma.parse_market(RAW)

        assert [o.label for o in parsed.outcomes] == ["Yes", "No"]
        assert [o.price for o in parsed.outcomes] == [0.62, 0.38]
        assert [o.token_id for o in parsed.outcomes] == ["111", "222"]

    def test_a_bare_comma_separated_string_is_also_accepted(self):
        assert gamma._maybe_json("Yes,No") == ["Yes", "No"]

    def test_an_unparseable_array_yields_nothing_rather_than_raising(self):
        """A market we cannot price is one we decline, not an exception."""
        assert gamma._maybe_json('["Yes", ') == []

    def test_a_market_with_no_question_is_declined(self):
        """
        Rendering it blank would invite the reader to think the market is empty
        rather than that we failed to read it.
        """
        assert gamma.parse_market({**RAW, "question": ""}) is None

    def test_an_absent_figure_is_unknown_rather_than_zero(self):
        parsed = gamma.parse_market({**RAW, "volumeNum": None, "volume": None})

        assert parsed.volume_usd is None

    def test_the_category_is_resolved_from_the_tag(self):
        assert gamma.parse_market(RAW).category == "politics"


class TestHolderPrivacy:
    def test_a_name_is_shown_only_when_its_owner_published_one(self):
        """
        When `displayUsernamePublic` is false the `name` field is the wallet
        address repeated. Rendering it as a display name would present an
        address as though somebody had chosen to be identified by it.
        """
        payload = [
            {
                "token": "111",
                "holders": [
                    {
                        "proxyWallet": "0xabc",
                        "name": "0xabc",
                        "pseudonym": "Webbed-Myth",
                        "displayUsernamePublic": False,
                        "amount": 10.0,
                        "outcomeIndex": 0,
                    },
                    {
                        "proxyWallet": "0xdef",
                        "name": "realname",
                        "displayUsernamePublic": True,
                        "amount": 20.0,
                        "outcomeIndex": 1,
                    },
                ],
            }
        ]

        holders = data_api.parse_holders(payload, ["Yes", "No"])

        assert holders[0].display_name == "realname"
        assert holders[1].display_name is None

    def test_the_outcome_index_is_resolved_to_its_label(self):
        """An index alone is meaningless once both tokens sit in one list."""
        payload = [{"holders": [{"proxyWallet": "0x1", "amount": 5.0, "outcomeIndex": 1}]}]

        assert data_api.parse_holders(payload, ["Yes", "No"])[0].outcome_label == "No"


class TestMicrostructure:
    def _facts(self, holders):
        return MarketFacts(
            market=MarketSummary(
                market_id="1",
                slug="s",
                question="q",
                outcomes=[Outcome(label="Yes", price=0.62), Outcome(label="No", price=0.38)],
            ),
            holders=holders,
        )

    def test_concentration_is_measured_within_one_outcome(self):
        """
        Pooling both sides would divide a Yes holder's stake by the total of two
        opposing books, which is not a share of anything.
        """
        holders = [
            Holder(wallet="a", outcome_label="Yes", shares=75.0),
            Holder(wallet="b", outcome_label="Yes", shares=25.0),
            Holder(wallet="c", outcome_label="No", shares=1000.0),
        ]

        micro = microstructure.summarise(self._facts(holders))

        assert micro.top_holder_share == 0.75

    def test_an_absent_holder_table_is_unknown_and_said_so(self):
        micro = microstructure.summarise(self._facts([]))

        assert micro.top_holder_share is None
        assert any("concentration is unknown" in note for note in micro.notes)

    def test_drift_is_anchored_to_the_series_not_the_wall_clock(self):
        """
        A market whose history stopped updating must report no drift rather
        than appear to have held perfectly steady through a gap in our data.
        """
        from datetime import UTC, datetime, timedelta

        base = datetime(2026, 3, 1, tzinfo=UTC)
        facts = self._facts([])
        facts.history = [
            PricePoint(t=base, p=0.40),
            PricePoint(t=base + timedelta(hours=30), p=0.55),
        ]

        assert microstructure.summarise(facts).drift_24h == 0.15


class TestBoardResilience:
    @pytest.fixture(autouse=True)
    def _clear(self):
        service.invalidate()
        yield
        service.invalidate()

    def test_a_failed_fetch_replays_the_last_good_board(self, monkeypatch):
        """
        A board two minutes old with its age shown beats an empty screen: the
        questions and their rough odds are still true.
        """
        monkeypatch.setattr(gamma, "fetch_markets", lambda **_: _ok())
        first = asyncio.run(service.get_board())
        assert first["count"] == 1 and first["stale"] is False

        service._cache._caches.clear()  # expire the TTL, keep the fallback

        async def boom(**_):
            raise RuntimeError("gamma down")

        monkeypatch.setattr(gamma, "fetch_markets", boom)
        replayed = asyncio.run(service.get_board())

        assert replayed["stale"] is True
        assert replayed["count"] == 1

    def test_a_failure_with_no_cache_is_an_outage_not_an_empty_board(self, monkeypatch):
        """
        A page handed `[]` renders the outage as the claim that nobody is
        betting on anything.
        """

        async def boom(**_):
            raise RuntimeError("gamma down")

        monkeypatch.setattr(gamma, "fetch_markets", boom)

        with pytest.raises(service.UpstreamUnavailable):
            asyncio.run(service.get_board())


async def _ok():
    return [RAW]
