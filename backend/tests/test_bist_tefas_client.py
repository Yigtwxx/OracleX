"""
The TEFAS client's boundary behaviour.

Three things here cost real time to discover and would cost it again if they
regressed silently:

* **The allocation payload.** `basSira`/`bitSira` missing, or a date in ISO
  instead of `yyyyMMdd`, both come back as HTTP 200 with a message that reads
  like a server fault. Nothing raises at the wrong layer; the board just empties.
* **A throttle is not an outage.** TEFAS answers a request arriving too soon in
  a different envelope entirely, and reading that as a failed upstream would
  mark the BIST health badge red for a service that is working.
* **Percentages become fractions at this boundary**, once, so nothing downstream
  has to remember which numbers are pre-multiplied.

Nothing here touches the network: `post_json` and `_post` are monkeypatched.
"""

from datetime import date

import httpx
import pytest

from services.bist import tefas_client
from services.bist.tefas_client import (
    ALLOCATION_FIELDS,
    TefasThrottled,
    TefasUnavailable,
    fetch_fund_allocations,
)


class TestAllocationPayload:
    def test_dates_are_yyyymmdd(self):
        payload = tefas_client._allocation_payload("YAT", date(2026, 8, 21), date(2026, 8, 28), 100)
        # ISO fails "at index 4" and dd.MM.yyyy "at index 0"; this is the only
        # format the endpoint parses.
        assert payload["basTarih"] == "20260821"
        assert payload["bitTarih"] == "20260828"

    def test_row_range_is_always_sent(self):
        payload = tefas_client._allocation_payload("YAT", date(2026, 8, 21), date(2026, 8, 28), 100)
        assert payload["basSira"] == 1
        assert payload["bitSira"] == 100

    def test_fund_code_is_null_because_the_endpoint_ignores_it(self):
        payload = tefas_client._allocation_payload("YAT", date(2026, 8, 21), date(2026, 8, 28), 100)
        assert payload["fonKodu"] is None
        assert payload["fonTipi"] == "YAT"


class TestPostEnvelopes:
    @pytest.mark.asyncio
    async def test_fault_code_body_is_a_throttle(self, monkeypatch):
        async def fake(*args, **kwargs):
            return {"faultCode": "ERR-224", "faultString": "Throttling limit"}

        monkeypatch.setattr(tefas_client, "post_json", fake)
        with pytest.raises(TefasThrottled):
            await tefas_client._post("https://example.invalid", {})

    @pytest.mark.asyncio
    async def test_http_429_is_a_throttle(self, monkeypatch):
        async def fake(*args, **kwargs):
            request = httpx.Request("POST", "https://example.invalid")
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError("throttled", request=request, response=response)

        monkeypatch.setattr(tefas_client, "post_json", fake)
        with pytest.raises(TefasThrottled):
            await tefas_client._post("https://example.invalid", {})

    @pytest.mark.asyncio
    async def test_other_status_is_a_plain_outage(self, monkeypatch):
        async def fake(*args, **kwargs):
            request = httpx.Request("POST", "https://example.invalid")
            response = httpx.Response(500, request=request)
            raise httpx.HTTPStatusError("boom", request=request, response=response)

        monkeypatch.setattr(tefas_client, "post_json", fake)
        with pytest.raises(TefasUnavailable) as caught:
            await tefas_client._post("https://example.invalid", {})
        assert not isinstance(caught.value, TefasThrottled)

    @pytest.mark.asyncio
    async def test_error_message_body_is_still_an_outage(self, monkeypatch):
        async def fake(*args, **kwargs):
            # What an unpublished date answers with. Indistinguishable from a
            # malformed request, which is why the fetcher asks for a window.
            return {"errorMessage": "Index 0 out of bounds for length 0", "resultList": None}

        monkeypatch.setattr(tefas_client, "post_json", fake)
        with pytest.raises(TefasUnavailable) as caught:
            await tefas_client._post("https://example.invalid", {})
        assert not isinstance(caught.value, TefasThrottled)


def _row(code: str, day: str, **weights) -> dict:
    row = {"fonKodu": code, "fonUnvan": f"{code} PORTFÖY FONU", "tarih": day}
    row.update(dict.fromkeys(ALLOCATION_FIELDS))
    row.update(weights)
    return row


class TestFetchAllocations:
    @pytest.mark.asyncio
    async def test_percentages_become_fractions(self, monkeypatch):
        async def fake(endpoint, payload):
            return [_row("DFI", "2026-08-28", hs=53.23, yyf=32, vmtl=14.51, fb=0.26)]

        monkeypatch.setattr(tefas_client, "_post", fake)
        rows = await fetch_fund_allocations("YAT")
        assert rows[0].weights["hs"] == pytest.approx(0.5323)
        assert rows[0].day == date(2026, 8, 28)

    @pytest.mark.asyncio
    async def test_unreported_lines_are_absent_not_zero(self, monkeypatch):
        async def fake(endpoint, payload):
            return [_row("DFI", "2026-08-28", hs=100.0, km=0.0)]

        monkeypatch.setattr(tefas_client, "_post", fake)
        rows = await fetch_fund_allocations("YAT")
        # A fund that holds no gold and a fund whose gold line was not published
        # are different claims, and neither of them is "0".
        assert set(rows[0].weights) == {"hs"}

    @pytest.mark.asyncio
    async def test_newest_day_wins_within_the_window(self, monkeypatch):
        async def fake(endpoint, payload):
            return [
                _row("DFI", "2026-08-26", hs=10.0),
                _row("DFI", "2026-08-28", hs=90.0),
                _row("DFI", "2026-08-27", hs=50.0),
            ]

        monkeypatch.setattr(tefas_client, "_post", fake)
        rows = await fetch_fund_allocations("YAT")
        assert len(rows) == 1
        assert rows[0].day == date(2026, 8, 28)
        assert rows[0].weights["hs"] == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_row_cap_is_a_failure_not_a_truncation(self, monkeypatch):
        async def fake(endpoint, payload):
            return [_row(f"F{i:05d}", "2026-08-28", hs=100.0) for i in range(25_000)]

        monkeypatch.setattr(tefas_client, "_post", fake)
        with pytest.raises(TefasUnavailable):
            await fetch_fund_allocations("YAT")

    @pytest.mark.asyncio
    async def test_unknown_fund_type_is_rejected_before_the_request(self):
        with pytest.raises(ValueError):
            await fetch_fund_allocations("NOPE")
