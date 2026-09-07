"""
The exchange ids, checked against the ccxt that is actually installed.

ccxt renames exchanges between releases, and a stale id fails silently here:
`_get_exchange_instance` returns None, `fetch_ticker` returns None like any
other missing quote, and the venue leaves the arbitrage board without a log
line or a health record. `coinbasepro`, `gateio` and `huobi` had all been gone
for releases before anyone noticed the US premium was missing from the spread.
"""

import ccxt

from services import ccxt_service


def test_every_default_exchange_exists_in_the_installed_ccxt():
    unknown = [name for name in ccxt_service.DEFAULT_EXCHANGES if getattr(ccxt, name, None) is None]

    assert unknown == [], f"ccxt {ccxt.__version__} does not know: {unknown}"


def test_every_default_exchange_has_a_display_entry():
    """
    `EXCHANGE_INFO` is what `/api/exchanges` advertises.

    A venue listed there but not queried, or queried but not listed, tells the
    UI something the board cannot deliver.
    """
    assert sorted(ccxt_service.EXCHANGE_INFO) == sorted(ccxt_service.DEFAULT_EXCHANGES)
