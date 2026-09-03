---
description: Price, technical levels and recent history for one symbol from a running Oracle-X instance
argument-hint: <symbol>  e.g. BTCUSDT, AAPL, ETHUSDT
allowed-tools: mcp__oracle-x__check_instance, mcp__oracle-x__get_price, mcp__oracle-x__get_technical_levels, mcp__oracle-x__get_symbol_history
---

Work up `$1` against the running Oracle-X instance.

1. `check_instance` first. If it does not answer, say the terminal is not
   running and stop — do not fall back on a remembered price.
2. `get_price` for the spot figure.
3. `get_technical_levels` for support, resistance, RSI and trend. **Report the
   zones as returned.** They are built per timeframe and scored by how many
   horizons confirm them; recomputing them from candles produces a different,
   worse answer that looks the same.
4. `get_symbol_history` for whether this setup has resolved before. This is the
   part a search engine cannot answer and the reason to ask the terminal.

A `404` means the symbol did not resolve, not that the price is unknown —
say so and check the venue prefix rather than substituting a guess. Crypto is
`BTCUSDT` or `BINANCE:ETHUSDT`; equities are the plain ticker. Borsa İstanbul
is a different plugin (`oracle-x-bist`) and a bare Turkish ticker will not
resolve here.

Close with the levels and what would invalidate them. Do not add a
recommendation the data does not carry.
