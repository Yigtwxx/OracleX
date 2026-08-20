"""What these tools must never do, regardless of what the instance says.

The failure this file guards is the one that costs a user money: a tool that
turns "the instance declined" or "the instance is not there" into something a
model reads as data. Every test below is a shape assertion on the result, not
a check that the HTTP call was made.

Upstreams are stubbed at the server module's import site — `server.client` —
rather than at httpx, matching the backend suite's convention.
"""

from __future__ import annotations

from typing import Any

import pytest

from oracle_x_mcp import server
from oracle_x_mcp.client import AuthRequired, InstanceUnreachable, NotFound, OracleXError


def _raiser(exc: Exception):
    async def _fail(*args: Any, **kwargs: Any) -> Any:
        raise exc

    return _fail


def _returner(value: Any):
    async def _ok(*args: Any, **kwargs: Any) -> Any:
        return value

    return _ok


class TestDeclinedIsNotAnError:
    """A 404 from Oracle-X is a deliberate answer, not a fault.

    The backend refuses to emit a placeholder price, so the tool has to hand
    the model something it can repeat to the user — and it must not look like
    a transport failure the model should retry.
    """

    async def test_unknown_symbol_reports_the_symbol_and_the_fix(self, monkeypatch):
        monkeypatch.setattr(server.client, "get", _raiser(NotFound("no data")))

        result = await server.get_price("NOTATICKER")

        assert result["ok"] is False
        assert "NOTATICKER" in result["reason"]
        # The most common cause is the symbol form, so the hint has to be there
        # or the model retries the same string.
        assert "BTCUSDT" in result["reason"]

    async def test_missing_levels_do_not_masquerade_as_data(self, monkeypatch):
        monkeypatch.setattr(server.client, "get", _raiser(NotFound("no data")))

        result = await server.get_technical_levels("XYZ")

        assert result["ok"] is False
        assert "zones" not in result


class TestUnreachableInstance:
    """No instance means every tool fails the same way, and says so."""

    async def test_check_instance_names_the_url_it_tried(self, monkeypatch):
        monkeypatch.setattr(
            server.client,
            "get",
            _raiser(InstanceUnreachable("No Oracle-X instance answering at http://x")),
        )

        result = await server.check_instance()

        assert result["ok"] is False
        assert "http://x" in result["reason"]

    async def test_a_data_tool_never_returns_a_shell_of_a_payload(self, monkeypatch):
        monkeypatch.setattr(server.client, "get", _raiser(InstanceUnreachable("down")))

        result = await server.get_market_overview()

        assert result == {"ok": False, "reason": "down"}


class TestAuthentication:
    """A missing token is a user action, not a retry."""

    async def test_watchlist_says_what_to_set(self, monkeypatch):
        monkeypatch.setattr(server.client, "get", _raiser(AuthRequired("Set ORACLE_X_TOKEN")))

        result = await server.get_watchlist()

        assert result["ok"] is False
        assert "ORACLE_X_TOKEN" in result["reason"]


class TestNewsAnalysis:
    """The cached read answers 200 with a null body when nothing exists yet.

    Testing the status code instead of the body is how a caller reports "no
    analysis available" for an article the terminal would analyse in twenty
    seconds, so the cache check has to be truthiness on the payload.
    """

    async def test_a_cached_analysis_is_returned_without_starting_a_job(self, monkeypatch):
        started = False

        async def _post(*args: Any, **kwargs: Any) -> Any:
            nonlocal started
            started = True
            return {"job_id": "j1"}

        monkeypatch.setattr(server.client, "get", _returner({"sentiment": "neutral"}))
        monkeypatch.setattr(server.client, "post", _post)

        result = await server.get_news_analysis("abc")

        assert result["ok"] is True
        assert result["sentiment"] == "neutral"
        assert started is False

    async def test_a_null_body_starts_a_job_rather_than_reporting_nothing(self, monkeypatch):
        calls: list[str] = []

        async def _get(path: str, *args: Any, **kwargs: Any) -> Any:
            calls.append(path)
            if path.endswith("/analysis"):
                return None  # the documented "not generated yet" answer
            return {"status": "completed", "result": {"sentiment": "bearish"}}

        monkeypatch.setattr(server.client, "get", _get)
        monkeypatch.setattr(server.client, "post", _returner({"job_id": "j1"}))
        monkeypatch.setattr(server.asyncio, "sleep", _returner(None))

        result = await server.get_news_analysis("abc")

        assert result["ok"] is True
        assert result["sentiment"] == "bearish"
        assert any("jobs" in path for path in calls)

    async def test_a_job_that_never_finishes_is_pending_not_failed(self, monkeypatch):
        async def _get(path: str, *args: Any, **kwargs: Any) -> Any:
            if path.endswith("/analysis"):
                return None
            return {"status": "running"}

        monkeypatch.setattr(server.client, "get", _get)
        monkeypatch.setattr(server.client, "post", _returner({"job_id": "j9"}))
        monkeypatch.setattr(server.asyncio, "sleep", _returner(None))

        result = await server.get_news_analysis("abc")

        assert result["pending"] is True
        assert result["job_id"] == "j9"


class TestAskOracle:
    """The expensive tool checks first and refuses to double-spend."""

    async def test_it_does_not_start_a_turn_when_no_provider_is_serving(self, monkeypatch):
        posted = False

        async def _post(*args: Any, **kwargs: Any) -> Any:
            nonlocal posted
            posted = True
            return {}

        monkeypatch.setattr(server.client, "get", _returner({"available": False}))
        monkeypatch.setattr(server.client, "post", _post)

        result = await server.ask_oracle("what now?")

        assert result["ok"] is False
        assert posted is False

    async def test_an_unfinished_turn_tells_the_caller_not_to_start_another(self, monkeypatch):
        async def _get(path: str, *args: Any, **kwargs: Any) -> Any:
            if path.endswith("status"):
                return {"available": True}
            return {"status": "running"}

        monkeypatch.setattr(server.client, "get", _get)
        monkeypatch.setattr(server.client, "post", _returner({"job_id": "c1"}))
        monkeypatch.setattr(server.asyncio, "sleep", _returner(None))

        result = await server.ask_oracle("what now?")

        assert result["pending"] is True
        assert "second turn" in result["reason"]


class TestToolSurface:
    async def test_every_tool_carries_a_description(self):
        tools = await server.server.list_tools()

        assert tools, "no tools registered"
        for tool in tools:
            # The description is the only thing a model sees when choosing.
            # An undescribed tool is one that never gets called.
            assert tool.description, f"{tool.name} has no description"
            assert len(tool.description) > 60, f"{tool.name} is described too thinly"

    async def test_no_tool_raises_through_the_transport(self, monkeypatch):
        """Every failure has to arrive as data.

        Raising gives the model a stack trace and an invitation to retry, and
        none of these conditions get better on a retry.
        """
        monkeypatch.setattr(server.client, "get", _raiser(OracleXError("boom")))
        monkeypatch.setattr(server.client, "post", _raiser(OracleXError("boom")))

        for name in ("get_price", "get_technical_levels", "get_liquidation_map"):
            result = await getattr(server, name)("BTCUSDT")
            assert result["ok"] is False

        for name in ("get_market_overview", "get_macro_regime", "get_chains_board"):
            result = await getattr(server, name)()
            assert result["ok"] is False


@pytest.mark.parametrize(
    "env,expected",
    [({}, "http://localhost:8000"), ({"ORACLE_X_URL": "http://h:1/"}, "http://h:1")],
)
def test_base_url_defaults_and_strips_trailing_slash(monkeypatch, env, expected):
    monkeypatch.delenv("ORACLE_X_URL", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    from oracle_x_mcp import client

    assert client.base_url() == expected


class TestLiquidationSummary:
    """The endpoint answers with a rendering grid; the tool must not pass it on.

    Two failures are guarded here. The size one is obvious — a few hundred
    kilobytes of heatmap cells in a model's context buys nothing. The other is
    not: the grid accumulates over time, so summing every column reports the
    same exposure several times over, and an occupied cell can still carry zero
    notional.
    """

    @staticmethod
    def _grid() -> dict[str, Any]:
        # Two time columns. The newer one is the current state; the older one
        # holds different numbers so a summariser that sums both is visible.
        return {
            "symbol": "BTC-USDT-SWAP",
            "price_min": 1000.0,
            "price_max": 2000.0,
            "bin_size": 100.0,
            "cells": [
                [0, 1, 5_000, 0],
                [0, 5, 7_000, 0],
                [1, 1, 900_000, 0],  # below spot
                [1, 5, 300_000, 0],  # below spot
                [1, 9, 0, 0],  # occupied but empty — must not be reported
            ],
            "candles": [{"close": 1900.0}],
        }

    def test_only_the_newest_column_counts(self):
        result = server._summarize_liquidation_map(self._grid(), top=5)

        assert result["ok"] is True
        # 900_000 + 300_000, not the older column's 12_000 as well.
        assert result["total_notional_usd"] == 1_200_000

    def test_zero_notional_bins_are_not_reported_as_clusters(self):
        result = server._summarize_liquidation_map(self._grid(), top=5)

        every = result["clusters_above"] + result["clusters_below"]
        assert every, "expected clusters"
        assert all(c["notional_usd"] > 0 for c in every)

    def test_an_empty_side_is_stated_rather_than_omitted(self):
        result = server._summarize_liquidation_map(self._grid(), top=5)

        # Everything in the fixture sits below 1900, so the upside is empty —
        # and that is a finding, not a gap in the lookup.
        assert result["clusters_above"] == []
        assert "above" in result["note"]

    def test_clusters_are_anchored_to_spot(self):
        result = server._summarize_liquidation_map(self._grid(), top=5)

        biggest = result["clusters_below"][0]
        assert biggest["notional_usd"] == 900_000
        assert biggest["price_low"] == 1100.0
        assert biggest["distance_percent"] < 0

    def test_a_grid_without_cells_is_a_failure_not_an_empty_answer(self):
        result = server._summarize_liquidation_map({"cells": []}, top=5)

        assert result["ok"] is False
