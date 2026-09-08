"""
Tests for AI usage accounting.

Nothing measured what the terminal spent before this: `profiles.ai_queries_today`
counted a route no client called, and the token figures every provider already
returns were read only by Ollama's truncation warning.
"""

import pytest

from services.llm import providers, usage
from services.usage_service import summarise


@pytest.fixture(autouse=True)
def clean_buffer():
    usage.drain()
    yield
    usage.drain()


class TestRecording:
    def test_records_into_the_buffer(self):
        usage.record(provider="groq", model="llama", prompt_tokens=10, completion_tokens=4)
        rows = usage.drain()
        assert len(rows) == 1
        assert rows[0].provider == "groq"
        assert rows[0].total_tokens == 14, "derived when the provider does not send a total"

    def test_a_provider_that_reports_nothing_records_none_not_zero(self):
        """ "Did not say" and "used none" are different facts."""
        usage.record(provider="mystery", model="m")
        row = usage.drain()[0]
        assert row.prompt_tokens is None
        assert row.completion_tokens is None
        assert row.total_tokens is None

    def test_an_explicit_total_is_kept(self):
        usage.record(
            provider="openai", model="m", prompt_tokens=10, completion_tokens=4, total_tokens=99
        )
        assert usage.drain()[0].total_tokens == 99

    def test_recording_never_raises(self):
        """It sits on the hot path of every reply."""
        usage.record(provider="x", model="y", prompt_tokens="not a number")  # type: ignore[arg-type]
        usage.drain()

    def test_the_buffer_is_bounded(self, monkeypatch):
        """A database outage must cost rows, not the process."""
        monkeypatch.setattr(usage, "MAX_BUFFER", 3)
        for i in range(10):
            usage.record(provider="p", model=str(i))
        rows = usage.drain()
        assert len(rows) == 3
        assert [r.model for r in rows] == ["7", "8", "9"], "keeps the newest"

    def test_restore_puts_rows_back_oldest_first(self):
        usage.record(provider="p", model="a")
        rows = usage.drain()
        usage.record(provider="p", model="b")
        usage.restore(rows)
        assert [r.model for r in usage.drain()] == ["a", "b"]


class TestAttribution:
    def test_unbound_context_is_background(self):
        """The schedulers carry no reader, and that is a real answer."""
        usage.record(provider="p", model="m")
        row = usage.drain()[0]
        assert row.user_id is None
        assert row.feature == "background"

    def test_binding_attributes_to_the_reader(self):
        tokens = usage.bind("user-1", "chat")
        try:
            usage.record(provider="p", model="m")
        finally:
            usage.reset(tokens)

        row = usage.drain()[0]
        assert row.user_id == "user-1"
        assert row.feature == "chat"

    def test_a_binding_does_not_survive_its_reset(self):
        """A reused worker task must not file the next reader's calls here."""
        tokens = usage.bind("user-1", "chat")
        usage.reset(tokens)
        usage.record(provider="p", model="m")
        assert usage.drain()[0].user_id is None

    def test_key_owner_defaults_to_the_server(self):
        usage.record(provider="p", model="m")
        assert usage.drain()[0].key_owner == "server"

    def test_key_owner_can_be_bound_to_the_reader(self):
        """A reader on their own key costs the operator nothing."""
        token = usage.bind_key_owner("user")
        try:
            usage.record(provider="p", model="m")
        finally:
            usage.reset_key_owner(token)

        assert usage.drain()[0].key_owner == "user"
        usage.record(provider="p", model="m")
        assert usage.drain()[0].key_owner == "server", "reset restores the default"


class TestProviderShapes:
    """Three vocabularies for the same two numbers."""

    @pytest.mark.parametrize(
        "payload,expected",
        [
            ({"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}, (10, 4, 14)),
            ({"input_tokens": 7, "output_tokens": 3}, (7, 3, 10)),
            ({"prompt_eval_count": 623, "eval_count": 7}, (623, 7, 630)),
            ({}, (None, None, None)),
            (None, (None, None, None)),
        ],
        ids=["openai", "anthropic", "ollama", "empty", "missing"],
    )
    def test_every_reported_shape_is_read(self, payload, expected):
        providers._record_usage("p", "m", payload)
        row = usage.drain()[0]
        assert (row.prompt_tokens, row.completion_tokens, row.total_tokens) == expected

    def test_duration_is_carried(self):
        providers._record_usage("p", "m", {"prompt_tokens": 1}, 1234)
        assert usage.drain()[0].duration_ms == 1234


class TestSummarise:
    def _row(self, **kw):
        base = {
            "feature": "chat",
            "provider": "groq",
            "key_owner": "server",
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "ok": True,
        }
        base.update(kw)
        return base

    def test_totals_add_up(self):
        summary = summarise(
            [self._row(), self._row(prompt_tokens=2, completion_tokens=1, total_tokens=3)]
        )
        assert summary["totals"]["requests"] == 2
        assert summary["totals"]["total_tokens"] == 18
        assert summary["totals"]["prompt_tokens"] == 12

    def test_failures_are_counted_separately(self):
        summary = summarise([self._row(), self._row(ok=False)])
        assert summary["totals"]["requests"] == 2
        assert summary["totals"]["failed"] == 1

    def test_rows_without_token_data_are_declared(self):
        """A total that undercounts has to say so rather than read as complete."""
        summary = summarise(
            [self._row(), self._row(prompt_tokens=None, completion_tokens=None, total_tokens=None)]
        )
        assert summary["totals"]["requests"] == 2
        assert summary["totals"]["total_tokens"] == 15
        assert summary["totals"]["requests_without_token_data"] == 1

    def test_breakdowns_split_by_feature_provider_and_payer(self):
        summary = summarise(
            [
                self._row(feature="chat", provider="groq", key_owner="user"),
                self._row(feature="notes", provider="ollama", key_owner="server"),
            ]
        )
        assert summary["by_feature"]["chat"]["requests"] == 1
        assert summary["by_feature"]["notes"]["requests"] == 1
        assert summary["by_provider"]["ollama"]["requests"] == 1
        assert summary["by_key_owner"]["user"]["total_tokens"] == 15

    def test_an_empty_history_summarises_to_zero(self):
        summary = summarise([])
        assert summary["totals"]["requests"] == 0
        assert summary["by_feature"] == {}


class TestFlushIsInertUnderTest:
    """
    Telemetry must never leave a test run.

    The suite exercises the real app including its shutdown, and shutdown
    flushes — six rows describing a stub provider named "gemini" with the model
    "m" reached the live project before this guard existed.
    """

    @pytest.mark.asyncio
    async def test_flush_writes_nothing_while_testing(self, monkeypatch):
        def explode():
            raise AssertionError("a test run must not reach the database")

        monkeypatch.setattr("services.supabase_service.get_supabase", explode)

        usage.record(provider="stub", model="m")
        assert await usage.flush() == 0

    @pytest.mark.asyncio
    async def test_the_buffer_is_still_drained(self):
        """Otherwise a long suite would grow it until the bound trimmed it."""
        usage.record(provider="stub", model="m")
        await usage.flush()
        assert usage.pending() == 0

    def test_recording_still_works_under_test(self):
        """Only the write is suppressed; everything up to it stays covered."""
        usage.record(provider="stub", model="m", prompt_tokens=5)
        assert usage.pending() == 1
