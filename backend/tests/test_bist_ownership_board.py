"""
Building the BIST ownership board and pivoting it three ways.

The seams worth pinning: a shareholder stake is *marked* at the equity board's
market cap and a fund position is *reported* from the filing, and the two are
labelled; a card that fails keeps yesterday's row and says so; a holder no
alias names stays on the company page as untracked and never becomes a card;
and the moves are the ownership-shaped filings on the tape, nothing else.

Nothing here reaches the network: the equity board, the card fetch, the fund
book and the KAP tape are all replaced at the module the board imports them
into.
"""

from __future__ import annotations

import os
from datetime import date

import pytest

from services.bist import holdings_service
from services.bist.equity_service import EquityBoard, EquityDataUnavailable
from services.bist.fund_holdings import Holding
from services.bist.kap_service import Disclosure
from services.bist.ownership import board, registry, snapshots
from services.bist.ownership.errors import BoardUnavailable, EntityNotFound, TickerNotCovered
from services.bist.ownership.isyatirim_client import CompanyCard, IsYatirimUnavailable, Shareholder
from services.bist.ownership.registry import EntityConfig
from services.bist.tradingview_client import EquityRow
from services.cache import bist_cache


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    bist_cache.clear()
    monkeypatch.setattr(board, "BOARD_FILE", os.path.join(tmp_path, "board.json"))
    monkeypatch.setattr(snapshots, "SNAPSHOT_FILE", os.path.join(tmp_path, "snapshots.json"))
    yield
    bist_cache.clear()


def _equity(ticker: str, name: str, market_cap: float | None, indices=("XU100",)) -> EquityRow:
    return EquityRow(
        ticker=ticker,
        symbol=f"BIST:{ticker}",
        name=name,
        price=10.0,
        change_pct=0.0,
        change_abs=0.0,
        volume=1.0,
        traded_value=1.0,
        market_cap=market_cap,
        pe=None,
        pb=None,
        ev_ebitda=None,
        free_float_pct=0.30,
        sector="Sektör",
        indices=tuple(indices),
    )


EQUITIES = [
    _equity("THYAO", "Türk Hava Yolları", 400e9),
    _equity("HALKB", "Halkbank", 300e9),
    _equity("KCHOL", "Koç Holding", 500e9),
    _equity("SMALL", "Küçük Şirket", 5e9, indices=("XUTUM",)),
]

CARDS = {
    "THYAO": CompanyCard(
        ticker="THYAO",
        shareholders=(Shareholder("Türkiye Varlık Fonu", 49.12),),
        other_pct=50.88,
        foreign_ratio_pct=22.71,
        free_float_pct=50.3,
        market_cap_try=416e9,
        url="https://www.isyatirim.com.tr/card?hisse=THYAO",
        retrieved_at="2026-09-02T06:00:00+00:00",
    ),
    "HALKB": CompanyCard(
        ticker="HALKB",
        shareholders=(Shareholder("Türkiye Varlık Fonu", 91.49),),
        other_pct=8.51,
        foreign_ratio_pct=0.68,
        free_float_pct=8.4,
        market_cap_try=None,
        url="https://www.isyatirim.com.tr/card?hisse=HALKB",
        retrieved_at="2026-09-02T06:00:00+00:00",
    ),
    "KCHOL": CompanyCard(
        ticker="KCHOL",
        shareholders=(
            Shareholder("Family Danışmanlık Gayrimenkul Ve Ticaret Anonim Ş", 43.75),
            Shareholder("Vehbi Koç Vakfı", 7.29),
        ),
        other_pct=42.81,
        foreign_ratio_pct=53.22,
        free_float_pct=26.3,
        market_cap_try=544e9,
        url="https://www.isyatirim.com.tr/card?hisse=KCHOL",
        retrieved_at="2026-09-02T06:00:00+00:00",
    ),
}

ENTITIES = [
    EntityConfig(
        id="tvf",
        name="Türkiye Varlık Fonu",
        category="state",
        order=10,
        aliases=("Türkiye Varlık Fonu",),
        sources={"shareholders": {}},
    ),
    EntityConfig(
        id="vkv",
        name="Vehbi Koç Vakfı",
        category="other",
        order=900,
        aliases=("Vehbi Koç Vakfı",),
        sources={"shareholders": {}},
    ),
    EntityConfig(
        id="fund-ak3",
        name="Ak Portföy Hisse Senedi Fonu",
        category="fund",
        order=500,
        sources={"kap_fund": {"code": "AK3"}},
    ),
]


def _fund_outcome(code: str) -> holdings_service.HoldingsOutcome:
    return holdings_service.HoldingsOutcome(
        holdings=holdings_service.FundHoldings(
            code=code,
            year=2026,
            period=7,
            published=date(2026, 8, 8),
            late=False,
            layout="lettered",
            holdings=(
                Holding(ticker="THYAO", label="TÜRK HAVA YOLLARI", value=2e9, weight=0.4),
                Holding(ticker="SMALL", label="KÜÇÜK ŞİRKET", value=3e9, weight=0.6),
            ),
            total_value=5e9,
            disclosure_url="https://www.kap.org.tr/tr/Bildirim/1",
        ),
        reason=None,
    )


def _disclosure(index: int, ticker: str, title: str, category: str = "ODA") -> Disclosure:
    return Disclosure(
        index=index,
        title=title,
        company=f"{ticker} A.Ş.",
        ticker=ticker,
        category=category,
        category_label="Özel Durum Açıklaması",
        published_at=f"2026-09-0{index}T10:00:00+03:00",
        summary="",
        is_late=False,
        url=f"https://www.kap.org.tr/tr/Bildirim/{index}",
    )


TAPE = [
    _disclosure(3, "THYAO", "Pay Alım Satım Bildirimi"),
    _disclosure(2, "KCHOL", "Finansal Rapor", category="FR"),
    _disclosure(1, "HALKB", "Sermaye Artırımı - Azaltımı İşlemlerine İlişkin Bildirim"),
]


@pytest.fixture
def stubbed(monkeypatch):
    async def equity_board():
        return EquityBoard(equities=EQUITIES, indices=[], stale=False, as_of="2026-09-02")

    async def card(ticker: str):
        try:
            return CARDS[ticker]
        except KeyError:
            raise IsYatirimUnavailable(f"no card for {ticker}") from None

    async def fund(code: str, fund_type: str = "YAT"):
        return _fund_outcome(code)

    async def tape(limit: int = 40, *, ticker=None, categories=None):
        return TAPE

    monkeypatch.setattr(board, "fetch_equity_board", equity_board)
    monkeypatch.setattr(board, "fetch_company_card", card)
    monkeypatch.setattr(holdings_service, "fetch_fund_holdings", fund)
    monkeypatch.setattr(board, "fetch_tape", tape)
    monkeypatch.setattr(registry, "load_entities", lambda: sorted(ENTITIES, key=lambda e: e.order))
    return monkeypatch


async def test_refresh_walks_the_universe_only_and_stores_the_payload(stubbed):
    report = await board.refresh_board(spacing=0)

    assert report.tickers_total == 3, "SMALL is not in the XU100 and gets no card"
    assert report.tickers_ok == 3
    assert report.funds_ok == 1
    assert board.board_age_seconds() is not None
    assert board.board_age_seconds() < 60


async def test_a_stake_is_marked_at_the_equity_boards_market_cap(stubbed):
    await board.refresh_board(spacing=0)

    detail = await board.get_entity("tvf")

    by_ticker = {p.ticker: p for p in detail.positions}
    assert by_ticker["THYAO"].stake_pct == pytest.approx(0.4912)
    # The equity board's 400bn, not the card's 416bn: one price source per
    # terminal, and the quote row already uses this one.
    assert by_ticker["THYAO"].value_try == pytest.approx(400e9 * 0.4912)
    assert by_ticker["THYAO"].value_basis == "marked"
    assert by_ticker["HALKB"].value_try == pytest.approx(300e9 * 0.9149)
    # Largest first, and the weights are shares of the entity's known value.
    assert detail.positions[0].ticker == "HALKB"
    assert sum(p.weight_pct for p in detail.positions) == pytest.approx(1.0)
    assert detail.entity.total_value_try == pytest.approx(400e9 * 0.4912 + 300e9 * 0.9149)


async def test_a_fund_position_is_reported_and_its_stake_derived(stubbed):
    await board.refresh_board(spacing=0)

    detail = await board.get_entity("fund-ak3")

    by_ticker = {p.ticker: p for p in detail.positions}
    assert by_ticker["THYAO"].value_try == 2e9
    assert by_ticker["THYAO"].value_basis == "reported"
    assert by_ticker["THYAO"].stake_pct == pytest.approx(2e9 / 400e9)
    # A holding outside the XU100 keeps its filed value and is still valued
    # against the whole equity board, which does carry the company.
    assert by_ticker["SMALL"].stake_pct == pytest.approx(3e9 / 5e9)
    assert by_ticker["SMALL"].name == "Küçük Şirket"
    assert detail.sources[0].kind == "kap_fund_report"
    assert detail.sources[0].as_of == "2026-07"


async def test_the_board_lists_every_entity_with_or_without_data(stubbed):
    await board.refresh_board(spacing=0)

    result = await board.get_board()

    assert [e.id for e in result.entities] == ["tvf", "fund-ak3", "vkv"]
    assert result.category_counts == {"state": 1, "fund": 1, "other": 1}
    assert result.tickers_covered == 3
    assert result.universe == "XU100"
    assert not result.stale
    assert all(s.ok for s in result.sources)


async def test_the_company_page_lists_untracked_holders_too(stubbed):
    await board.refresh_board(spacing=0)

    owners = await board.get_asset_owners("BIST:KCHOL")

    assert owners.foreign_ratio_pct == pytest.approx(0.5322)
    assert owners.free_float_pct == pytest.approx(0.30), "the equity row's fraction, as-is"
    assert [h.label for h in owners.holders] == [
        "Family Danışmanlık Gayrimenkul Ve Ticaret Anonim Ş",
        "Vehbi Koç Vakfı",
    ]
    family, vakif = owners.holders
    assert not family.tracked and family.entity_id is None
    assert vakif.tracked and vakif.entity_id == "vkv"
    assert family.value_try == pytest.approx(500e9 * 0.4375)


async def test_the_company_page_names_the_funds_that_hold_it(stubbed):
    await board.refresh_board(spacing=0)

    owners = await board.get_asset_owners("THYAO")

    assert [f.code for f in owners.funds] == ["AK3"]
    assert owners.funds[0].weight_in_fund_pct == pytest.approx(0.4)
    assert owners.funds[0].stake_pct == pytest.approx(2e9 / 400e9)


async def test_a_ticker_outside_the_universe_is_not_covered(stubbed):
    await board.refresh_board(spacing=0)

    with pytest.raises(TickerNotCovered):
        await board.get_asset_owners("SMALL")


async def test_moves_are_only_the_ownership_shaped_filings(stubbed):
    await board.refresh_board(spacing=0)

    result = await board.get_board()

    # The financial report on KCHOL is not an ownership event.
    assert [m.ticker for m in result.latest_moves] == ["THYAO", "HALKB"]
    assert result.latest_moves[0].event == "icsel_islem"
    assert result.latest_moves[1].event == "sermaye"

    tvf = await board.get_entity("tvf")
    assert [m.id for m in tvf.moves] == ["kap-3", "kap-1"]
    assert tvf.entity.last_move is not None and tvf.entity.last_move.id == "kap-3"

    vkv = await board.get_entity("vkv")
    assert vkv.moves == []


async def test_a_failed_card_keeps_yesterdays_row_and_says_so(stubbed):
    await board.refresh_board(spacing=0)

    async def failing(ticker: str):
        if ticker == "THYAO":
            raise IsYatirimUnavailable("boom")
        return CARDS[ticker]

    stubbed.setattr(board, "fetch_company_card", failing)
    report = await board.refresh_board(spacing=0)

    assert report.tickers_failed == 1 and report.tickers_carried == 1
    owners = await board.get_asset_owners("THYAO")
    assert owners.holders[0].stake_pct == pytest.approx(0.4912)
    assert owners.stale, "a carried row is old data and the page must say so"
    result = await board.get_board()
    isyatirim = next(s for s in result.sources if s.kind == "isyatirim_shareholders")
    assert not isyatirim.ok
    assert "taşındı" in (isyatirim.message or "")


async def test_a_card_that_never_loaded_is_unavailable_not_empty(stubbed):
    async def failing(ticker: str):
        if ticker == "THYAO":
            raise IsYatirimUnavailable("boom")
        return CARDS[ticker]

    stubbed.setattr(board, "fetch_company_card", failing)
    await board.refresh_board(spacing=0)

    with pytest.raises(BoardUnavailable):
        await board.get_asset_owners("THYAO")


async def test_no_board_is_an_error_not_an_empty_list(stubbed):
    with pytest.raises(BoardUnavailable):
        await board.get_board()
    with pytest.raises(BoardUnavailable):
        await board.get_asset_owners("THYAO")


async def test_an_unknown_entity_is_not_found(stubbed):
    await board.refresh_board(spacing=0)

    with pytest.raises(EntityNotFound):
        await board.get_entity("nobody")


async def test_refresh_needs_the_equity_board_to_value_anything(stubbed):
    async def no_board():
        raise EquityDataUnavailable("down")

    stubbed.setattr(board, "fetch_equity_board", no_board)

    with pytest.raises(BoardUnavailable):
        await board.refresh_board(spacing=0)


async def test_ensure_board_builds_only_when_missing_or_old(stubbed):
    calls = 0

    async def counting(**kwargs):
        nonlocal calls
        calls += 1
        return board.RefreshReport()

    stubbed.setattr(board, "refresh_board", counting)

    await board.ensure_board()
    assert calls == 1

    stubbed.setattr(board, "board_age_seconds", lambda: 60.0)
    await board.ensure_board()
    assert calls == 1

    stubbed.setattr(board, "board_age_seconds", lambda: 40 * 3600.0)
    await board.ensure_board()
    assert calls == 2


async def test_first_snapshot_knows_no_entry_dates(stubbed):
    await board.refresh_board(spacing=0)

    detail = await board.get_entity("tvf")
    owners = await board.get_asset_owners("THYAO")

    assert detail.tracking_since == snapshots.baseline_day()
    assert all(p.at_baseline and p.since == detail.tracking_since for p in detail.positions)
    assert all(p.delta_pct is None for p in detail.positions), "one snapshot, no delta"
    assert detail.stake_moves == []
    assert owners.holders[0].at_baseline and owners.holders[0].delta_pct is None


async def test_a_second_day_reveals_entries_exits_and_resizes(stubbed):
    # Yesterday's tables, written as the previous refresh would have. TVF held
    # less of THYAO, a holder in KCHOL has since gone, and HALKB was unchanged.
    snapshots.record(
        "2020-01-01",
        {
            "THYAO": {"ok": True, "holders": [{"label": "Türkiye Varlık Fonu", "stake_pct": 0.45}]},
            "HALKB": {
                "ok": True,
                "holders": [{"label": "Türkiye Varlık Fonu", "stake_pct": 0.9149}],
            },
            "KCHOL": {
                "ok": True,
                "holders": [
                    {
                        "label": "Family Danışmanlık Gayrimenkul Ve Ticaret Anonim Ş",
                        "stake_pct": 0.4375,
                    },
                    {"label": "Gone Holding", "stake_pct": 0.06},
                ],
            },
        },
    )
    await board.refresh_board(spacing=0)

    detail = await board.get_entity("tvf")
    by_ticker = {p.ticker: p for p in detail.positions}
    assert by_ticker["THYAO"].delta_pct == pytest.approx(0.4912 - 0.45)
    assert by_ticker["THYAO"].previous_stake_pct == 0.45
    assert by_ticker["HALKB"].delta_pct == 0.0
    assert by_ticker["THYAO"].at_baseline, "already there on day one — entry date unknown"
    assert [(m.ticker, m.kind) for m in detail.stake_moves] == [("THYAO", "add")]
    assert detail.stake_moves[0].entity_id == "tvf"

    owners = await board.get_asset_owners("KCHOL")
    vakif = next(h for h in owners.holders if h.label == "Vehbi Koç Vakfı")
    assert not vakif.at_baseline, "absent yesterday, present today: a real entry"
    assert [(m.holder, m.kind) for m in owners.stake_moves] == [
        ("Gone Holding", "exit"),
        ("Vehbi Koç Vakfı", "new"),
    ]
    assert owners.stake_moves[0].entity_id is None, "an untracked holder still gets its exit"

    result = await board.get_board()
    assert result.tracking_since == "2020-01-01"
    assert {m.kind for m in result.latest_stake_moves} == {"add", "exit", "new"}
