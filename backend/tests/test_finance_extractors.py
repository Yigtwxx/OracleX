"""
Reading a financial page that is a table rather than an article.

The extractors will break — five sites, and selectors rot. What these tests pin
is not that a particular selector works today but that a *broken* one degrades
the right way: `None` and a stated gap, never a confident wrong number.
"""

import pytest

from services import finance_extractors as fx

CMC_HTML = """
<html><head><title>Bitcoin price</title></head><body>
<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"detailRes":{"detail":{"name":"Bitcoin","statistics":
{"price":64231.55,"priceChangePercentage24h":-1.82,"marketCap":1268000000000,
"volume":31200000000,"circulatingSupply":19700000,"rank":1}}}}}}
</script>
</body></html>
"""

TRADINGVIEW_HTML = """
<html><head><meta property="og:title" content="BTCUSD Chart"/>
<script type="application/ld+json">
{"@type":"FinancialProduct","name":"Bitcoin / US Dollar","price":"64231.55",
 "priceCurrency":"USD","tickerSymbol":"BTCUSD"}
</script></head><body></body></html>
"""

FINVIZ_HTML = """
<html><head><title>NVDA</title></head><body><table>
<tr><td>Price</td><td>178.42</td></tr>
<tr><td>P/E</td><td>54.10</td></tr>
<tr><td>Forward P/E</td><td>32.80</td></tr>
<tr><td>Market Cap</td><td>4.35T</td></tr>
<tr><td>EPS (ttm)</td><td>3.30</td></tr>
</table></body></html>
"""


# ── routing ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://coinmarketcap.com/currencies/bitcoin/", True),
        ("https://www.coinmarketcap.com/currencies/bitcoin/", True),
        ("https://www.tradingview.com/symbols/BTCUSD/", True),
        ("https://finviz.com/quote.ashx?t=NVDA", True),
        ("https://uk.investing.com/indices/us-30", True),
        ("https://finance.yahoo.com/quote/NVDA", True),
        ("https://www.coindesk.com/markets/story", False),
        ("https://example.com/", False),
        ("not a url", False),
    ],
)
def test_only_known_hosts_are_read_as_data(url, expected):
    assert fx.has_extractor(url) is expected


def test_an_unknown_host_extracts_nothing():
    assert fx.extract(CMC_HTML, "https://example.com/x") is None


def test_empty_html_extracts_nothing():
    assert fx.extract("", "https://coinmarketcap.com/currencies/bitcoin/") is None


# ── the extractors ───────────────────────────────────────────────────────────


def test_coinmarketcap_reads_its_own_data_layer():
    extraction = fx.extract(CMC_HTML, "https://coinmarketcap.com/currencies/bitcoin/")

    assert extraction is not None
    assert extraction.kind == "quote"
    assert "Bitcoin" in extraction.title
    assert "64,231.55" in extraction.fields["Price"]
    assert extraction.fields["Rank"] == "1"


def test_tradingview_reads_the_json_ld_the_server_does_emit():
    extraction = fx.extract(TRADINGVIEW_HTML, "https://www.tradingview.com/symbols/BTCUSD/")

    assert extraction is not None
    assert extraction.fields["Symbol"] == "BTCUSD"
    assert "64,231.55" in extraction.fields["Price"]


def test_finviz_reads_its_snapshot_table():
    extraction = fx.extract(FINVIZ_HTML, "https://finviz.com/quote.ashx?t=NVDA")

    assert extraction is not None
    assert extraction.kind == "screener"
    assert "P/E" in extraction.fields


def test_a_rendered_block_labels_every_figure():
    extraction = fx.extract(CMC_HTML, "https://coinmarketcap.com/currencies/bitcoin/")
    rendered = extraction.render()

    for label in extraction.fields:
        assert f"- {label}:" in rendered


# ── how it breaks ────────────────────────────────────────────────────────────


def test_a_redesign_yields_nothing_rather_than_wrong_numbers():
    """
    The property that makes this safe to ship. A page whose markup no longer
    matches must produce no reading at all — a stated gap is recoverable, a
    confident wrong price is not.
    """
    redesigned = "<html><body><div>everything moved</div></body></html>"

    for url in (
        "https://coinmarketcap.com/currencies/bitcoin/",
        "https://www.tradingview.com/symbols/BTCUSD/",
        "https://finviz.com/quote.ashx?t=NVDA",
        "https://uk.investing.com/indices/us-30",
        "https://finance.yahoo.com/quote/NVDA",
    ):
        assert fx.extract(redesigned, url) is None


def test_one_stray_number_is_not_a_reading():
    """Below `MIN_FIELDS` it is more likely a parsing accident than a quote."""
    thin = '<html><script id="__NEXT_DATA__">{"statistics":{"price":1}}</script></html>'

    assert fx.extract(thin, "https://coinmarketcap.com/currencies/bitcoin/") is None


def test_an_extractor_that_raises_is_not_a_failed_turn(monkeypatch):
    def _boom(_html, _url):
        raise RuntimeError("selector exploded")

    monkeypatch.setitem(fx.EXTRACTORS, "coinmarketcap.com", _boom)

    assert fx.extract(CMC_HTML, "https://coinmarketcap.com/currencies/bitcoin/") is None


def test_an_oversized_blob_is_not_parsed():
    """An unbounded JSON parse on a page that turned out to be hostile."""
    huge = (
        '<html><script id="__NEXT_DATA__">' + ("x" * (fx.MAX_JSON_CHARS + 10)) + "</script></html>"
    )

    assert fx.extract(huge, "https://coinmarketcap.com/currencies/bitcoin/") is None


# ── the shared parser ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("64,231.55", 64231.55),
        ("$1,268,000,000,000", 1268000000000.0),
        ("1.234,56", 1234.56),  # European grouping
        ("0,01%", 0.01),  # Turkish decimal comma
        ("-1.82%", -1.82),
        ("(1.82%)", -1.82),  # a fall, written without a minus
        ("", None),
        (None, None),
        ("no digits here", None),
    ],
)
def test_number_parsing(text, expected):
    assert fx.parse_number(text) == expected


def test_a_layout_change_returns_none_not_zero():
    """
    The distinction the whole module rests on: a market cannot be told apart
    from a parser at zero, and every caller renders the two differently.
    """
    assert fx.parse_number("Price unavailable") is None


def test_the_module_does_no_io():
    """
    Purity is what makes this safe: the HTML was fetched by a rung that went
    through `url_guard`, and an extractor that fetched anything would be outside
    that guarantee.
    """
    with open(fx.__file__, encoding="utf-8") as handle:
        imports = [line.strip() for line in handle if line.startswith(("import ", "from "))]

    for line in imports:
        assert not any(
            module in line
            for module in ("httpx", "requests", "aiohttp", "scrapling", "url_guard", "http_client")
        ), line
