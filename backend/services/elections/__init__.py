"""
The elections board: what votes are scheduled, and what the market prices them at.

An election is a volatility catalyst in the same class as an FOMC decision, so
this package answers a trader's three questions rather than a civics one — when,
what is priced, and what to watch. Three layers, each owning exactly one of them:

* `wikipedia` owns *when*. It is the only source consulted for a polling date.
* `registry` owns *who that country is and why it matters* — the tracked seed
  file that turns Wikipedia's country string into a flag and a ticker list.
* `odds` and `join` own *what it is priced at*, from Polymarket.

The split is not decorative. Gamma reports a market's `endDate`, which is its
*resolution* date and routinely days off the vote — "Next French Presidential
Election" carries 30 April 2027 for an election held on the 18th. Reading a
polling date off a prediction market would put a wrong date on the board, and a
wrong date is the one failure this panel cannot recover from.
"""

from services.elections.service import fetch_elections

__all__ = ["fetch_elections"]
