"""
Assembling a fund's equity book from KAP, and refusing clearly when it cannot.

The seam that matters here is not the happy path — that is one call each — it is
the five ways there can be no book, which have to stay five and not collapse
into one. A fund with no filing, a fund holding no stocks, a filing this parser
cannot read and a KAP outage produce different sentences on the page, and only
one of them means the fund owns nothing.

The other seam is cost. Four upstream calls per fund against a host that
rate-limits is affordable only because the answer is cached hard and a failure
starts a cooldown, so the tests pin both.

Nothing here touches the network: `kap_fund_client` is monkeypatched at the
module the service imports it into, and the PDF parse is stubbed with text.
"""

from datetime import date

import pytest

from services.bist import fund_holdings, holdings_service, kap_fund_client
from services.bist.holdings_service import fetch_fund_holdings
from services.cache import bist_cache


@pytest.fixture(autouse=True)
def _clean_cache():
    # The holdings cache is a module singleton keyed by fund code, so without
    # this a test that primes it answers for every test after it.
    bist_cache.clear()
    yield
    bist_cache.clear()


CATALOGUE = {"AAA": kap_fund_client.FundRef(code="AAA", oid="oid-aaa", name="AAA PORTFÖY FONU")}


def _report(period: int, index: int) -> kap_fund_client.PortfolioReport:
    return kap_fund_client.PortfolioReport(
        fund_code="AAA",
        index=index,
        year=2026,
        period=period,
        published=date(2026, period + 1, 8),
        late=False,
    )


ATTACHMENT = kap_fund_client.Attachment(obj_id="obj-1", file_name="rapor.pdf", extension="pdf")

READABLE = """
3- FON PORTFÖY DEĞERİ TABLOSU
 A) HİSSE SENETLERİ
    THYAO   TÜRK HAVA YOLLARI   100.000,00   30.000.000,00   60,00%
    ASELS   ASELSAN A.Ş.         50.000,00   10.000.000,00   20,00%
 B) VARANTLAR
"""

BOND_ONLY = """
III-FON PORTFÖY DEĞERİ TABLOSU
BORÇLANMA SENETLERİ
TRFAKYM82610  TL  AK YATIRIM  16.000.000,00  17.664.178,30  1,13
MEVDUAT
"""


def _wire(
    monkeypatch,
    *,
    catalogue=CATALOGUE,
    reports=None,
    attachment=ATTACHMENT,
    text=READABLE,
    downloads=None,
):
    """Patch the four upstream calls. `text` may be a per-disclosure mapping."""
    calls = {"catalogue": 0, "reports": 0, "download": 0}

    async def fake_catalogue(fund_type="YAT"):
        calls["catalogue"] += 1
        if isinstance(catalogue, Exception):
            raise catalogue
        return catalogue

    async def fake_reports(oids, *, fund_type="YAT", since, until):
        calls["reports"] += 1
        if isinstance(reports, Exception):
            raise reports
        return list(reports or [])

    async def fake_attachment(index):
        return attachment

    async def fake_download(obj_id):
        calls["download"] += 1
        if isinstance(downloads, Exception):
            raise downloads
        return b"%PDF-fake%%EOF"

    def fake_parse(pdf):
        body = text(calls["download"]) if callable(text) else text
        return fund_holdings.parse_equity_holdings(body) if body is not None else None

    monkeypatch.setattr(kap_fund_client, "fetch_fund_catalogue", fake_catalogue)
    monkeypatch.setattr(kap_fund_client, "fetch_portfolio_reports", fake_reports)
    monkeypatch.setattr(kap_fund_client, "fetch_attachment", fake_attachment)
    monkeypatch.setattr(kap_fund_client, "download_report", fake_download)
    monkeypatch.setattr(fund_holdings, "parse_pdf", fake_parse)
    return calls


class TestReading:
    @pytest.mark.asyncio
    async def test_returns_the_newest_book(self, monkeypatch):
        _wire(monkeypatch, reports=[_report(7, 100), _report(6, 99)])
        outcome = await fetch_fund_holdings("AAA")
        assert outcome.reason is None
        assert outcome.holdings.period == 7
        assert [h.ticker for h in outcome.holdings.holdings] == ["THYAO", "ASELS"]

    @pytest.mark.asyncio
    async def test_links_back_to_the_filing(self, monkeypatch):
        _wire(monkeypatch, reports=[_report(7, 1646134)])
        outcome = await fetch_fund_holdings("AAA")
        assert outcome.holdings.disclosure_url.endswith("/tr/Bildirim/1646134")

    @pytest.mark.asyncio
    async def test_falls_back_to_the_previous_month_when_the_newest_is_unreadable(
        self, monkeypatch
    ):
        # A house's newest filing being unreadable is a parser gap, not a reason
        # to leave that fund permanently blank when last month's is the same
        # layout and readable.
        _wire(
            monkeypatch,
            reports=[_report(7, 100), _report(6, 99)],
            text=lambda call: None if call == 1 else READABLE,
        )
        outcome = await fetch_fund_holdings("AAA")
        assert outcome.reason is None
        assert outcome.holdings.period == 6

    @pytest.mark.asyncio
    async def test_the_answer_is_cached(self, monkeypatch):
        calls = _wire(monkeypatch, reports=[_report(7, 100)])
        await fetch_fund_holdings("AAA")
        await fetch_fund_holdings("AAA")
        assert calls["reports"] == 1


class TestRefusals:
    @pytest.mark.asyncio
    async def test_a_fund_kap_does_not_list(self, monkeypatch):
        _wire(monkeypatch, catalogue={})
        outcome = await fetch_fund_holdings("AAA")
        assert outcome.reason == holdings_service.REASON_NOT_LISTED
        assert outcome.holdings is None

    @pytest.mark.asyncio
    async def test_a_fund_with_no_filing(self, monkeypatch):
        _wire(monkeypatch, reports=[])
        outcome = await fetch_fund_holdings("AAA")
        assert outcome.reason == holdings_service.REASON_NO_REPORT

    @pytest.mark.asyncio
    async def test_a_fund_that_holds_no_equity(self, monkeypatch):
        # Distinct from `unreadable`: this report was read, and it says the fund
        # owns no stocks. Saying "could not be read" here would be false.
        _wire(monkeypatch, reports=[_report(7, 100)], text=BOND_ONLY)
        outcome = await fetch_fund_holdings("AAA")
        assert outcome.reason == holdings_service.REASON_NO_EQUITY

    @pytest.mark.asyncio
    async def test_a_layout_the_parser_cannot_read(self, monkeypatch):
        _wire(monkeypatch, reports=[_report(7, 100), _report(6, 99)], text=None)
        outcome = await fetch_fund_holdings("AAA")
        assert outcome.reason == holdings_service.REASON_UNREADABLE

    @pytest.mark.asyncio
    async def test_a_non_pdf_attachment_is_skipped(self, monkeypatch):
        _wire(
            monkeypatch,
            reports=[_report(7, 100)],
            attachment=kap_fund_client.Attachment(
                obj_id="obj-1", file_name="rapor.xlsx", extension="xlsx"
            ),
        )
        outcome = await fetch_fund_holdings("AAA")
        assert outcome.reason == holdings_service.REASON_UNREADABLE

    @pytest.mark.asyncio
    async def test_a_disclosure_with_no_attachment_is_skipped(self, monkeypatch):
        _wire(monkeypatch, reports=[_report(7, 100)], attachment=None)
        outcome = await fetch_fund_holdings("AAA")
        assert outcome.reason == holdings_service.REASON_UNREADABLE

    @pytest.mark.asyncio
    async def test_an_outage_is_named_as_one(self, monkeypatch):
        _wire(monkeypatch, reports=kap_fund_client.KapUnavailable("down"))
        outcome = await fetch_fund_holdings("AAA")
        assert outcome.reason == holdings_service.REASON_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_an_empty_code_is_rejected(self):
        with pytest.raises(ValueError):
            await fetch_fund_holdings("   ")


class TestCost:
    @pytest.mark.asyncio
    async def test_a_failure_starts_a_cooldown(self, monkeypatch):
        # Without it every reader refreshing a page that failed is another
        # request against a host that rate-limits — which is what turns one
        # outage into a longer one.
        calls = _wire(monkeypatch, reports=kap_fund_client.KapUnavailable("down"))
        await fetch_fund_holdings("AAA")
        await fetch_fund_holdings("AAA")
        assert calls["reports"] == 1

    @pytest.mark.asyncio
    async def test_the_previous_book_survives_an_outage(self, monkeypatch):
        _wire(monkeypatch, reports=[_report(7, 100)])
        await fetch_fund_holdings("AAA")

        # Expire the live entry and the cooldown, leaving the fallback — the
        # state a reader arrives in hours into an outage.
        bist_cache.invalidate("holdings:AAA")
        bist_cache.invalidate("holdings:cooldown:AAA")
        _wire(monkeypatch, reports=kap_fund_client.KapUnavailable("down"))

        outcome = await fetch_fund_holdings("AAA")
        assert outcome.stale is True
        assert outcome.holdings is not None
        assert [h.ticker for h in outcome.holdings.holdings] == ["THYAO", "ASELS"]


class TestUnwrapPdf:
    """
    Lives here rather than in its own file: it is one function, and the reason
    it exists is the download step this service depends on.
    """

    def test_finds_the_pdf_inside_the_java_wrapper(self):
        # KAP answers `content-type: application/pdf` with a serialised byte[],
        # which is why this is located by the PDF's own markers and not by the
        # 27-byte offset that serialiser happens to produce.
        raw = bytes.fromhex("aced0005757200025b42") + b"%PDF-1.4 body %%EOF" + b"\x78\x70"
        assert kap_fund_client.unwrap_pdf(raw) == b"%PDF-1.4 body %%EOF"

    def test_a_plainly_served_pdf_falls_out_of_the_same_path(self):
        assert kap_fund_client.unwrap_pdf(b"%PDF-1.7 body %%EOF") == b"%PDF-1.7 body %%EOF"

    def test_a_spreadsheet_is_not_a_pdf(self):
        assert kap_fund_client.unwrap_pdf(b"PK\x03\x04 xlsx") is None
