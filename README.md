<div align="center">
  <img src="docs/brand/oracle-x-mark.svg" width="96" height="96" alt="Oracle-X" />

  <h1 align="center">Oracle-X Financial Intelligence Terminal</h1>

  <p align="center">
    <strong>A unified terminal for equities and digital assets.</strong><br>
    <em>Market data, news reasoning and persistent memory in one surface, on an LLM layer you choose — local or cloud.</em>
  </p>

  <p align="center">
    <a href="#system-architecture"><img src="https://img.shields.io/badge/Architecture-Distributed-000000?style=flat-square&logo=cisco&logoColor=white" alt="Architecture" /></a>
    <a href="#tech-stack"><img src="https://img.shields.io/badge/Stack-Next.js%2014%20%7C%20FastAPI-38B2AC?style=flat-square&logo=next.js&logoColor=white" alt="Stack" /></a>
    <a href="#the-reasoning-layer"><img src="https://img.shields.io/badge/AI_Engine-14_providers%20%7C%20local_first-000000?style=flat-square&logo=ollama&logoColor=white" alt="AI Engine" /></a>
    <a href="#core-capabilities"><img src="https://img.shields.io/badge/Memory-ChromaDB_RAG_v5-FF6F00?style=flat-square&logo=databricks&logoColor=white" alt="RAG" /></a>
    <br/>
    <a href="https://github.com/Yigtwxx/OracleX/releases/latest"><img src="https://img.shields.io/badge/Release-v1.3.0-brightgreen?style=flat-square" alt="Release" /></a>
    <img src="https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey?style=flat-square" alt="Platform" />
    <a href="#quality-gates"><img src="https://img.shields.io/badge/CI-ruff%20%7C%20pytest%20%7C%20tsc%20%7C%20vitest-2088FF?style=flat-square&logo=githubactions&logoColor=white" alt="CI" /></a>
    <img src="https://img.shields.io/badge/Keys-encrypted_at_rest-success?style=flat-square" alt="Encrypted keys" />
    <img src="https://img.shields.io/badge/License-MIT-blue?style=flat-square" alt="License" />
    <img src="https://img.shields.io/badge/PRs-Welcome-ff69b4?style=flat-square" alt="PRs Welcome" />
  </p>
</div>

<details>
  <summary>Table of Contents</summary>
  <ol>
    <li><a href="#overview">Overview</a></li>
    <li><a href="#core-capabilities">Core Capabilities</a></li>
    <li><a href="#system-architecture">System Architecture</a></li>
    <li><a href="#directory-structure">Directory Structure</a></li>
    <li><a href="#tech-stack">Tech Stack</a></li>
    <li><a href="#installation">Installation</a></li>
    <li><a href="#running-with-docker">Running with Docker</a></li>
    <li><a href="#environment-configuration">Environment Configuration</a></li>
    <li><a href="#api-reference">API Reference</a></li>
    <li><a href="#quality-gates">Quality Gates</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#security">Security</a></li>
  </ol>
</details>

---

## Overview

Traders, quantitative analysts and financial researchers work across several
tools at once: one for equities, another for crypto, a third for charts, and a
social feed for sentiment. Each switch costs time, and nothing carries context
across the boundary.

Oracle-X is an open-source intelligence terminal that puts those sources on one
screen. Real-time WebSockets, background scheduling, a persistent vector store
and a provider-agnostic reasoning layer let it do more than display the data —
it relates each piece to the history behind it.

The AI layer is local-first but not local-only. The default configuration
reasons entirely on your machine through [Ollama](https://ollama.com); a single
environment variable switches it to Groq, Gemini, Anthropic, OpenAI or any other
supported provider, behind an ordered fallback chain so one provider's outage or
rate limit is not the terminal's outage.

**Two realms, one terminal.** The global board covers digital assets and US
equities; a second one covers Borsa İstanbul, in Turkish, against Turkish
inflation. They share the shell, the auth layer and the LLM chain and nothing
else — different upstreams, different tab set, different language — and a
switcher in the nav chrome moves between them. Which realm you are in is read
off the path rather than held in a store, so a link lands on the tab set its URL
asks for.

**Routes.** `/`, `/borsa`, `/developers` and `/faq` are the public site. The
global terminal lives under `/home`, `/overview`, `/dashboard`, `/analysis`,
`/chat`, `/heatmap`, `/live`, `/derivatives`, `/chains`, `/macro`,
`/polymarket`, `/ownership`, `/social`, `/community`, `/profile` and `/admin`;
the BIST realm under `/bist`, `/bist/hisseler`, `/bist/isi-haritasi`,
`/bist/fonlar`, `/bist/akilli-para`, `/bist/kap`, `/bist/viop`,
`/bist/viop-haritasi` and `/bist/makro`.

---

## Core Capabilities

### 1. Cross-Asset Market Matrix

Equities and digital assets are treated as one universe rather than two
integrations.

* **Equities (NASDAQ/NYSE):** live market caps, forward P/E ratios, analyst
  target bounds, margins and free cash flow, via Yahoo Finance `quoteSummary`
  HTTP modules.
* **Digital assets:** real-time price streaming and protocol metrics through
  CoinGecko V3 and the OKX public API.
* **Live asset registry:** which coins the overview shows, which stocks the
  NASDAQ page ranks and which pairs the socket streams are all resolved at
  runtime from CoinGecko / NASDAQ / OKX, never from a hardcoded list.
  Resolution degrades through an on-disk cache to a minimal emergency seed, so
  a cold start during an upstream outage still renders.
* **Asset detail modal:** 30+ data points per asset in one view — an equity's
  debt-to-equity ratio or a protocol's trailing four-week GitHub commit volume,
  without leaving the chart.
* **Followed-asset brief:** the top of `/home` is three reader-chosen slots, not
  a wall of market-wide cards. Each carries a price, a sparkline, a liquidity
  ladder placing the standing leverage above and below spot, and one grounded
  sentence. The market-wide readings the old block spent a screen on are a
  single line above it, in the same palette `/overview`'s stats bar uses — a
  reader who learns the colours on one page should not have to relearn them on
  the other.
* **Market internals:** three panels below the overview table answer what an
  aggregate stats bar cannot — advancing versus declining counts and the A/D
  ratio, median against mean against cap-weighted change, volume concentration,
  a fixed-bucket histogram of 24h moves that doubles as a click-to-filter
  control on the table above it, and a divergence board of liquid assets whose
  day contradicts their week. All of it is derived in `lib/market-breadth.ts`
  from the payload the table already holds, so the panels cost no extra request.
  The histogram edges never rescale: an axis that redraws itself cannot be
  compared to the chart you saw a minute ago, and an empty tail is information.
* **Multi-timeframe technical read:** every asset is analysed on three horizons
  at once — 4h/1d/1w for crypto, 1h/1d/1w for equities — each keeping its own
  RSI, ATR, trend and swing structure. Support and resistance are returned as
  **zones**, not decimals: bands built by clustering swing points within an
  ATR-scaled tolerance, carrying a touch count and a strength score, so one new
  candle no longer moves "the level". Weekly history is capped at two years on
  purpose — a 2017 level describes a market that no longer exists. A timeframe
  with too little history is dropped and named in `coverage` rather than
  extrapolated, and if none survives the endpoint reports a gap instead of a
  number.

### 2. News Intelligence Pipeline

Keyword matching produces too many false positives for financial news, so
ingestion runs through the model instead.

* **Ingestion:** an `APScheduler` job polls global feeds every
  `NEWS_FETCH_INTERVAL_MINUTES` (default **2 min**) — Tree of Alpha, Decrypt,
  CoinDesk, CoinTelegraph, The Block, CryptoSlate, Koin Bülteni and Uzmancoin
  for crypto; MarketWatch, Investing.com and Seeking Alpha for equities.
* **Semantic ticker extraction:** article text is piped through the configured
  model, and `symbol_detection_service` fuses that with the live asset registry
  so headlines map to real tickers. `SYMBOL_DETECTION_CONCURRENCY` caps
  concurrency so a 150-item refresh never floods the provider.
* **Attribution memory:** a headline's asset is a property of its text, so it is
  resolved once and cached to disk (`news_attribution`). A restart does not
  re-bill the backlog, and a story can no longer be filed under BTC at 10:00 and
  ETH at 10:02. Results from the degraded heuristic path are marked and
  revisited.
* **Sentiment scoring:** bullish / bearish / neutral with a 0–100 confidence
  score. With no provider reachable, the pipeline degrades to heuristic
  extraction rather than failing.
* **Per-article research notes:** opening a headline starts a staged pipeline
  (`Gathering evidence → Judging price impact`) that fetches the full article
  body — with a hard timeout, a per-host circuit breaker and paywall-stub
  rejection — merges it with technical levels and market context, and returns a
  verdict. Technical levels are copied verbatim from
  `technical_analysis_service`; the model is never asked to invent a price.
  Finished analyses are persisted and keyed by pipeline version, so a prompt
  edit retires the cache instead of serving stale reasoning indefinitely.

### 3. RAG Memory Stack (v1 – v5)

A ChromaDB vector store with `qwen3-embedding:0.6b` embeddings turns every
ingested article and price tick into queryable memory. Retrieval is three-stage:
vector search fused with BM25 by reciprocal rank, a relevance floor calibrated
per collection, then a `bge-reranker-v2-m3` cross-encoder that reads the query
against each candidate. Measured on `backend/evals/golden_set.jsonl`, the
cross-encoder alone moves recall@5 from 0.79 to 0.96.

* **v1 — outcome memory** (`rag_service.py`): one collection linking historical
  news to the price outcome that followed. Feeds the `/api/analyze` flow.
* **v2 — temporal core** (`rag_v2_service.py`): the primary store, split into
  `historical_news`, `market_events` and `price_history` collections with up to
  365 days of indexed history and event correlation.
* **v3 — insights agent:** answers *"why did BTC move on this date?"* —
  price-movement reasoning, historical news similarity, event-at-date lookup.
* **v4 — reasoning agent:** two-asset comparison and what-if scenario
  simulation.
* **v5 — proactive agent:** generates the daily morning brief and flags
  price-vs-news anomalies without being asked.

Retrieval is scored rather than ranked by proximity alone. `rag_scoring.py`
composes recency (per-collection half-lives), move magnitude, event class and
symbol relevance behind a calibrated cosine floor (`RAG_MIN_RELEVANCE`, measured
with `scripts/calibrate_rag_relevance.py` rather than guessed). `rag_outcomes.py`
measures what an event actually did across **1/7/30/90/180/365-day horizons**
plus max drawdown and run-up, because a 7-day window labels both the XRP–SEC
suit and the NVDA–DeepSeek crash backwards. Precedents whose outcome
contradicted their headline are boosted, since those are the ones with something
to teach. `rag_bellwethers.py` bounds the cost by spending that measurement on
the assets that set market direction.

### 4. Oracle Chat Agent

A conversational analyst wired into the memory stack. A turn is not one call to
a model — it is intent classification, tool selection, evidence gathering, a
bounded self-check, and only then an answer.

* **Intent before tools.** `chat_intent.py` labels each turn as one of thirteen
  behavioural intents (`conceptual`, `causal`, `comparative`, `scenario`,
  `macro`, `derivatives`, `ownership`, `portfolio`, `briefing`, …), in Turkish
  and English side by side. A name only earns a row if it changes which tools
  are offered or which rules the answer is held to. This is what makes *"what is
  a funding rate"* answerable: it resolves no asset, so under the old
  keyword tables no tool ran, no evidence block was built, and the turn prompt's
  rule that every figure must appear in context left the model correctly
  concluding it had nothing admissible to say. `evals/eval_refusal.py` is the
  metric for exactly that failure.
* **Conversational focus.** `chat_focus.py` resolves the subject from the recent
  *user* turns rather than only the last message, so *"peki RSI'ı?"* after
  *"BTC nasıl?"* still means BTC. Intents that are not about an asset's present
  state (`conceptual`, `macro`, `greeting`, `offtopic`, `briefing`) deliberately
  clear the inherited focus instead of dragging it forward.
* **Model-chosen tools, from a capped catalogue.** `CHAT_PLANNER_ENABLED` is now
  on: the model picks from a catalogue filtered by intent and capped at
  `MAX_CATALOGUE_TOOLS` (8, or 6 in concise mode) out of ~20 — small enough for
  a local model to choose well. Every failure path still lands on
  `heuristic_plan`, which is itself intent-routed. `evals/eval_planner.py`
  measures tool recall and precision before the flag is trusted.
* **A reflection round.** `CHAT_REFLECTION_ENABLED` adds one bounded second look
  at whether the gathered evidence actually answers the question, and one chance
  to fix it. Kept behind its own flag so it can be reverted independently of the
  planner.
* **Cross-session memory.** `chat_memory_service.py` persists the handful of
  facts that are true across conversations — that someone trades futures rather
  than spot, that they want short answers — into a narrow key/value table
  (`supabase/migrations/014_chat_memory.sql`). The write is proposed by a model,
  so the shape is the defence: only `ALLOWED_KEYS` are storable, never free text.
* **Reading pages, not just searching them.** The scrape ladder gained a data
  rung: for hosts that publish a grid of labelled numbers rather than prose
  (TradingView, Finviz, CoinMarketCap), `finance_extractors.py` reads the figures
  out of the HTML the prose extractor would have discarded. `read_chart`,
  `read_page` and `social_search` — Reddit, X, StockTwits, TradingView — are now
  actually reachable, bounded by `CHAT_MAX_SCRAPES_PER_TURN` and
  `CHAT_MAX_BROWSER_PER_TURN`.
* Routes each question across RAG v2/v3/v4 plus live web search, then synthesizes
  with the configured model. Every leg is time-boxed independently, so a slow
  source degrades the answer instead of hanging it.
* Full session management — conversations, message history and renames persist
  in Supabase. Long turns run as pollable jobs (`POST /api/chat/jobs`) that can
  be cancelled.
* Available as a dedicated page and as a global sidebar from anywhere in the
  terminal.

### 5. Staged Market Reports

`/api/analysis` produces daily / weekly / monthly reports through a four-stage
pipeline — `collecting → synthesis → drafting → review`.

* Stage 1 is pure Python: `analysis_data.py` assembles nine independent feeds
  into one deterministic snapshot and computes breadth, ratios and deltas
  itself, so arithmetic never reaches the model. A failing feed is recorded in
  `unavailable` rather than aborting the run.
* Stages 2–4 extract evidence, draft the report, then fact-check the draft back
  against the same snapshot, striking figures the data does not support.
* Generation is never triggered by a read. Callers `POST` a job and poll it; a
  second caller for the same timeframe joins the in-flight run instead of
  starting a duplicate.

### 6. Real-Time and Derivatives Data

* **Live price socket:** the frontend subscribes to Oracle-X's own `/ws/prices`
  endpoint, which fans out `ccxt.pro` exchange WebSocket streams to every
  connected client — one upstream connection, N browsers. The venue is
  configurable via `STREAM_EXCHANGE` (default **OKX**, because Binance is
  unreachable from several countries and fails on `load_markets()` before a
  single tick arrives).
* **Liquidation engine:** a long-running OKX liquidation WebSocket collector
  maintains rolling 24h history with disk persistence, powering the live feed
  and per-symbol levels.
* **Liquidation map:** a heatmap rebuilt from free OKX endpoints (candles, open
  interest, long/short account ratio). It models where leveraged positions would
  be force-closed — a different thing from the realised-liquidation feed above.
* **Derivatives board (`/derivatives`):** four views of the same leverage, kept
  apart because they answer different questions. **Open interest against price**
  is the input the other three model from — the pairing of the two directions is
  what says whether a move was positions being opened or closed, and neither
  column states it alone. The **standing liquidation book** is drawn against
  *price* rather than against time, so the question it answers is how far spot
  has to travel to reach a wall. **Historical lines** and the realised feed sit
  beside it. And the **on-chain venue panels** name whose book it is: a
  perpetual DEX publishes its open interest where a centralised venue reports
  it. Those three rankings are drawn as three panels and never joined into a
  table — a venue can lead one and be absent from another, and each names its
  own provider.
* **Funding rates and arbitrage:** perpetual funding rates on the home
  dashboard, plus a CCXT-backed multi-exchange price comparison and arbitrage
  scanner.

### 7. Chain Telemetry Board

`/chains` is the state of the rails underneath the market: eight networks read
live, on one board, priced in the coin their fees are actually paid in.

* **Eight chains, four adapter families.** Bitcoin, Ethereum, Base, Arbitrum,
  Optimism, BNB Smart Chain, Solana and Tron, through `evm`, `bitcoin`, `solana`
  and `tron` readers behind a single `registry.py` that holds only protocol
  constants and endpoints — anything that can differ between two polls is
  measured, never stored.
* **Comparable fees.** The same unit of work priced eight ways: a 21,000-gas
  native transfer on EVM chains, a 141-vbyte P2WPKH spend on Bitcoin, one
  signature on Solana. OP-stack rollups add the L1 data fee the block header
  does not carry, because execution cost alone understates what a transaction
  there really costs.
* **A gap is rendered as a gap.** Arbitrum publishes a `gasLimit` of 2^50 as a
  sentinel rather than a capacity, so `gasUsed / gasLimit` reads 0.00001% and a
  fullness bar would show a permanently idle chain. Chains flagged
  `gas_ceiling=False` report no fullness at all. A labelled gap is honest; a
  zero is not.
* **Partial failure costs one row.** Eight independent providers will not all be
  up at once, so every adapter is gathered with `return_exceptions=True` and a
  failure is recorded as `error` on that chain alone. The board never 503s, and
  an unreachable chain is visibly distinct from a quiet one. If the whole
  assembly fails it replays the last good board rather than returning nothing.
* **Anomaly detection in Python, commentary from the model.** `anomaly.py`
  computes what is unusual — fees at triple their usual level, load away from
  baseline, a difficulty swing — and ships each flag with a sentence written in
  Python, so the board keeps explaining itself with no provider reachable. Two
  independent baselines, because they fail independently: 30 days of Coin
  Metrics dailies (works on a cold start), and `history.py`'s own rolling
  samples, which correct for the fact that request-path sampling is as diurnal
  as gas prices are.
* **Exchange flows, honestly scoped.** Daily BTC and ETH exchange in/outflow
  from the Coin Metrics Community API. Coverage is two chains because the free
  tier answers 403 for the rest — the strip names its own limit rather than
  showing six zeros.

### 8. Prediction Markets

`/polymarket` reads the highest-volume open markets on Polymarket and treats a
crowd-priced probability as evidence to be examined, not as an answer.

* **Facts before any model.** A market's dialog opens on figures computed
  without an LLM: outcome prices, 24h and 7d drift, volume, liquidity, spread,
  top-holder concentration, and the dated windows in which the price actually
  re-priced. `moves.py` measures those in **absolute probability points**, never
  percentages — 0.02 → 0.04 is +100% and means nothing, while 0.45 → 0.62 is 17
  points and had a cause. A move must clear both a floor and three times that
  market's own median move before it is called sharp.
* **The analysis is allowed to refuse.** `sufficiency.py` decides whether the
  model is asked for a verdict at all, and it is a floor test rather than a
  weighted score — a score lets a pile of weak amplification outvote real
  corroboration. Distinct *domains* is the load-bearing floor, and the app's own
  RAG output deliberately does not count as a tier-1 source, because prior
  output cannot corroborate itself. Below the floors the endpoint answers
  `insufficient_evidence` and names every search that came back empty, in a
  paragraph written in Python: a model asked to explain its own thinness writes
  prose indistinguishable from the analysis it just withheld. The facts and
  microstructure are served either way, which is what keeps a refusal from
  reading as a broken page.
* **Claims are pruned mechanically.** The model returns `{text, sources}`
  objects rather than prose, so dropping an unsupported claim is a lookup and
  not a judgement. Invented source ids are deleted whole; a claim may cite the
  market's own price, but only if every figure in it appears verbatim in the
  rendered facts. Fewer than three survivors discards the synthesis rather than
  showing it thin, and the panel says how many claims were dropped.
* **Two jobs, never chained.** "Why was this bet opened" runs as its own trace,
  matching dated reporting against the measured move windows, and is allowed to
  end in a labelled conjecture. It is kept out of the verdict prompt on purpose:
  by the time a verdict is written, a conjecture is indistinguishable from
  evidence.
* **Trader geography does not exist, so the map says so.** The exchange settles
  on Polygon and identifies a counterparty only by `proxyWallet`, so no public
  endpoint anywhere carries a bettor's location and a bets-by-country choropleth
  cannot honestly be drawn. The map instead ships three layers that each name
  their own provenance and refuse to be merged: where it can legally be traded
  (transcribed from the geoblock list), what the questions are *about* (volume
  attributed to the country a question names, split rather than duplicated
  across multi-country questions), and when the money moves (traded value by
  hour of UTC day, drawn as bands rather than country shading).
* **Gamma's arrays are strings.** `outcomes`, `outcomePrices` and `clobTokenIds`
  arrive JSON-encoded, so `market["outcomePrices"][0]` is the character `[`.
  Nothing raises; the board simply fills with plausible nonsense. Everything
  crossing that boundary goes through `gamma._maybe_json`.

### 9. Alternative Data

* **Fear & Greed index** synchronized across the UI.
* **Macro regime read:** `macro_regime.py` scores equity breadth, the dollar and
  copper-against-gold — each voting -1/0/+1 through a deadband so a flat tape
  does not flip the read every refresh — into one word: risk-on, risk-off or
  neither. The label is computed in Python; the model only writes the sentence
  explaining it, and never sees a number that has not already been rounded to
  the grain the label was decided on. Crude is deliberately unscored (rising oil
  is growth or margin squeeze depending on the cause), and the components the
  board does not carry — rates, credit spreads, equity volatility — are named in
  the note rather than papered over.
* **Nothing Ever Happens index:** a companion novelty from the same publisher,
  reading a curated basket of high-impact geopolitical prediction markets rather
  than pizza queues. The reading is recomputed here from the source's own raw
  probabilities instead of copied from its gauge, so a change in how the source
  renders itself cannot silently redefine what the panel claims. It is the
  **highest** probability in the basket, never the mean — 27 mostly dormant
  markets average to a number that never moves, and the point of the gauge is
  the one market that is moving — and thin markets are excluded, because a 2%
  print with no depth behind it is a quote, not a probability.
* **Elections board:** upcoming national elections worldwide on `/macro`, with
  the calendar parsed from Wikipedia's yearly electoral-calendar articles and
  live odds joined in from Polymarket where a market can be matched to a row
  with confidence. The match is gated in two tiers: a structured country signal
  *and* a plausible resolution date renders a price, and anything weaker renders
  only a link. Thin markets are demoted to link-only on volume and liquidity
  floors. The two halves fail independently — losing the calendar is a 503,
  because an empty board would assert that no election is scheduled anywhere on
  Earth, while losing the odds is a 200 with a badge saying so. The payload also
  carries its own coverage cap, since Polymarket's listing is volume-ordered and
  most calendar rows genuinely having no market is not the same claim as
  "Polymarket covers nothing".
* **Pentagon Pizza Index:** an OSINT novelty gauge derived from late-evening
  activity at the pizza restaurants around the Pentagon, computed here from each
  venue's own baseline curve rather than copied from the source's own verdict.
  It renders as one badge in the nav chrome, at the size a novelty reading earns,
  and every surface that shows it carries the caveat.
* **On-chain flows:** whale transfers and exchange inflow/outflow tracking
  (optional Etherscan key).
* **Institutional ownership:** 13F-style holdings tracking with per-entity
  boards and historical snapshots, plus a flow note summarising what the tracked
  institutions actually did last quarter — counted from filed 13F moves only, so
  a corporate treasury topping up its bitcoin never becomes "institutions
  bought".
* **Developer velocity and social graph:** GitHub commit/issue velocity and
  community growth surfaced in the asset detail modal.

### 10. Borsa İstanbul Realm

A second terminal on the same shell, in Turkish, for Borsa İstanbul, TEFAS and
the Turkish macro series behind them. It is not the global board with the
tickers swapped, because the question is not the same one: **a lira figure
describes a number of lira, not what they bought**, and over the windows this
realm reports on — a year, three, five — the difference between those two
statements is most of the number.

* **Every return carries a real one.** `real_return.py` deflates each nominal
  figure in two frames, because they answer different questions: against TÜFE,
  which says what the money bought, and against USDTRY, which says what it was
  worth to someone who could have held dollars instead. Neither is "the" answer
  and the board never picks one silently. A Sharpe ratio computed against a zero
  risk-free rate is standard practice where the policy rate is 2%; against a TRY
  policy rate it is arithmetic about a fund nobody could have bought, so the
  rate is a parameter here rather than a constant.
* **One request is the whole equity board.** TradingView's public market scanner
  returns every listed BIST name with price, volume, market capitalisation, the
  valuation multiples and the index memberships in a single POST — which is why
  it is the source and not the four the plan originally called for. KAP's
  company list moved behind an app that answers an empty array to every request
  an ordinary client can construct, and borsaistanbul.com publishes constituents
  as dated files. Sector performance is *derived from the constituents* rather
  than read from XUSIN, XUTEK and XGIDA: those exist at the exchange but not in
  the quote source, and deriving them is both available and closer to the board
  the reader is looking at. Opening a company therefore costs nothing the
  screener has not already paid for.
* **The heatmap keeps size fixed.** Area is market capitalisation and colour is
  whichever metric the reader picks — the same division the crypto board makes,
  for the same reason: the one quantity that should not move when the reader
  changes the question is size. The toolbar offers four indices of the seven the
  API accepts; the other three are subsets a reader reaches for by name.
* **Funds: TEFAS for how much, KAP for which.** The board is one request for
  every fund TEFAS lists; a fund's risk statistics need its price series and
  that endpoint has no bulk form, so they are computed per fund on open. TEFAS
  publishes a portfolio across 54 instrument codes — drawn literally that is 54
  hairline segments and a reader learns nothing — so `fund_allocation.py`
  collapses them into a dozen buckets grouped by *economic exposure* where the
  field names it and by wrapper where the wrapper is all it names, which is what
  lets the bar answer the question it exists for: is this an equity fund, a bond
  fund, or a money-market fund wearing a different name. Which equities a fund
  holds appears only in its monthly KAP portfolio report, as a PDF whose JSON
  body carries the cover sheet and not one holding row — so that read is lazy,
  per fund, cached for a day, and written to refuse rather than to guess.
* **KAP is the primary source, and it is walked, not queried.** The disclosure
  tape has no usable public API: the documented endpoints were retired and the
  query page streams its rows rather than fetching JSON, so `kap_service` walks
  sequential `/tr/Bildirim/<index>` pages. Sixty rows all look alike — a title,
  a company, a timestamp — and a capital increase is not close in consequence to
  a weekly fund form, so `kap_materiality.py` puts a class and a band on every
  row **without a model**: labelling sixty rows with an LLM would run it
  continuously to produce a column, and the local model is the constraint here.
  The model writes one thing, on demand — a note on the single filing a reader
  opened. That note is the only one in the codebase narrating a *primary
  source* rather than a board: not "what do these figures mean together" but
  what a `pay geri alım` resolution actually does to the share count.
* **Exchange measures come out of the same tape.** Circuit breakers, gross
  settlement and short-selling bans are filed as ordinary disclosures with fixed
  titles and there is no feed of measures on its own, so they are filtered out
  of a deliberately over-wide window — a short one returns an empty radar on a
  quiet morning that is not actually quiet.
* **VİOP is read twice, on purpose.** A broker's public page is scraped during
  the session for nineteen underlyings with no history; Borsa İstanbul's own
  end-of-day bulletin carries forty-seven single-stock underlyings across three
  expiries, one file per session, archived years back. Different cadence, shape
  and failure mode, so they stay separate services. The open-interest column is
  why the board exists at all: it is the one place in the Turkish market where
  positioning is published rather than inferred.
* **The margin map is the crypto liquidation map with its weakest joint
  removed.** That model invents how leverage is distributed across users, because
  no exchange publishes what leverage its users chose. Here the clearing house
  publishes one Price Scan Range per underlying that binds everyone, every day —
  so a cohort gets one band and that band sits where a published parameter puts
  it. Exposure opened, entry price and open-interest change are all read rather
  than inferred. Two details are load-bearing: the day's SPAN file lives on
  `wwwdata.takasbank.com.tr`, a separate host from the bot-protected website, and
  reading it costs two filters (`setlMeth == "DELIV"`, and a `pfCode` that does
  not end in `_C`) or THYAO's scan range reads 14.0 instead of 13.4. Beside it,
  `spot_volume_profile.py` draws where volume was *actually* traded, from hourly
  bars over two years — the honest counterpart layer, with nothing modelled.
* **It draws a scan range and says it is not a call level.** VİOP publishes no
  maintenance margin rate: the CCP procedure leaves the level to a General Letter
  and states maintenance is not applied at end of day, so the price at which a
  margin call actually triggers cannot be computed from anything public. The
  "75% of initial" figure that circulates appears only in an undated guide. The
  page therefore draws the move a position's initial margin was sized for, and
  says so in as many words.
* **Positioning is narrower than it was meant to be, and says which part.** The
  intent was a fund-to-stock cross index — the Turkish counterpart of the 13F
  board on the global realm. TEFAS publishes a fund's split by *asset class* and
  nothing public names the individual securities behind "hisse senedi %58", so
  the board that shipped is crowding, futures quadrants, the 52-week range and
  sector heat, with the gap named rather than approximated.
* **Macro degrades to keyless.** With no configuration at all the realm reads
  the inflation rate, the policy rate and the exchange rate from the same scanner
  the equity board uses — enough for the figure that matters most, a one-year
  return deflated by one-year inflation, and for dollar-based returns over any
  window from a public USDTRY chart endpoint.
* **Gece Mesaisi Endeksi.** This realm's answer to the Pentagon Pizza Index, and
  the same class of claim: how hard the state is legislating today, read off the
  Resmî Gazete, and whether anything was urgent enough to skip the queue. Like
  the pizza gauge its endpoint cannot fail — it feeds a badge in the chrome of
  every BIST page, so a government site that stops answering must not be able to
  take those pages down with it, and the service answers `unavailable` for the
  badge to render as its own state.
* **Two Turkish details that fail silently if you get them wrong.**
  `str.casefold` cannot know which language it is looking at, so `"KESİCİ"`
  folds to an ASCII `i` followed by a combining dot while `"Kesici"` folds to
  plain `kesici` — the two never match, and no error is raised; `text.py` does
  the folding for the whole package. And `www.resmigazete.gov.tr` and
  `www.tccb.gov.tr` send their leaf certificate and stop, omitting the
  intermediate: browsers fetch the missing one from the leaf's AIA extension and
  httpx does not, so every request failed while the same URL opened fine in a
  browser.

### 11. Grounded Notes

Ten surfaces — the macro, chain and ownership boards, the followed-asset brief,
and five on the BIST realm — render deterministic figures and used to leave the
reader to work out what they meant. `services/ai_notes.py` closes that gap
without moving any arithmetic into the model.

* Each caller computes its own labels, thresholds and deltas in Python and hands
  the engine a finished set of facts. The model's only job is to say what they
  mean in a sentence or two.
* **Facts are the cache key.** A note is fingerprinted by the prompt it was
  written from and the facts it was written about, so identical facts reuse the
  note and a prompt edit retires every note derived from it — the same
  discipline the news-analysis cache uses.
* **A missing note is never an error state.** It is commentary on figures that
  are always present, so a page with no note is still complete. `lib/ai-note.ts`
  holds that branch on the frontend, where it is tested.
* **Figures are quantized before they are fingerprinted**, and the prompt is
  rendered from those same rounded values — so a cached note cannot cite a
  number that has since moved a decimal place under it.
* **One note is not commentary on a board.** `prompts/notes/kap_disclosure.md`
  narrates a company's own filing, in its own words, which the tape prints as a
  title and leaves unexplained. Every other note explains figures the reader can
  already see; that one explains a mechanism they may not carry.

### 12. Accounts, Community and Bring-Your-Own-Key

* Supabase Auth (email/password and Google OAuth). **Authorization is enforced
  in the application layer** (`dependencies/auth.py`): the backend holds the
  service-role key and therefore bypasses RLS, so every user-scoped endpoint
  takes its identity from a verified bearer token, never from a client-supplied
  `user_id`.
* A community feed with posts, threaded comments, likes and moderation, plus an
  admin surface with audit logging.
* User profiles carrying subscription tier, connected accounts, preferences and
  an AI query quota.
* **Per-user LLM settings:** each user can pick their own provider and model and
  supply their own API key, scoped to chat, news and/or reports. Keys are
  encrypted with Fernet before they reach Supabase (`services/secret_box.py`)
  and are returned to the UI only as a hint, never in plaintext.

### 13. Alarm Centre

The bell in the nav chrome opens a workspace for watching twelve sources —
price, 24h change, BTC dominance, funding, liquidations, Fear & Greed, the
Nothing Ever Happens index, chain anomalies, the Pentagon Pizza Index, news
keywords, macro events and prediction markets — under four kinds of condition: a
threshold, a server-computed state, a keyword match, or a countdown to an event.

* **Evaluation is entirely client-side.** `useAlarmEngine` ticks once every 15
  seconds and reads through the React Query cache using each source's own
  interval as `staleTime`, so an alarm piggybacks on requests the terminal was
  making anyway instead of opening its own. The decision itself is a pure
  function in `lib/alarms/evaluate.ts` returning trigger / rearm / none, which
  is where it is tested; the hook makes no decisions.
* **Nothing fires twice for one move.** A latched hysteresis band, sized as a
  *fraction* of the threshold so the same constant works for a 0.0001 funding
  rate and a six-figure BTC price, plus a bounded dedupe ring for event-shaped
  readings and a per-alarm cooldown. A stale reading never re-triggers, and a
  source reporting `unavailable` counts as no reading rather than as zero.
* **Mail is the only part the backend touches.** `routers/alarms.py` exists
  because a browser cannot speak SMTP. An address confirms itself with a code
  first; the browser then holds an HMAC bound to that address, compared in
  constant time; and the message body is composed server-side from a Jinja
  template. A stolen token therefore buys nothing but alarm-shaped mail to its
  own inbox. Delivery stays off until `SMTP_HOST` is set — an admin can set it
  from the panel or from the environment — and the UI hides the panel rather
  than offering a button that cannot work.
* **The other three channels need no configuration at all.** A toast, a Web
  Audio beep and an OS notification fire locally; mail is a fourth, sent
  fire-and-forget so a slow relay never delays the alarm itself.
* **Alarms live in the browser, not the database.** No migration, no table:
  definitions, history and the confirmed address persist to `localStorage`. The
  store carries a versioned migration that folds the old single-symbol price
  alerts into the new model and deletes the dead key, because `persist` shallow-
  merges and would otherwise resurrect it forever.

### 14. Boot Gate

A cold start touches a dozen upstreams. Rather than assembling itself panel by
panel over half a minute, the terminal holds its first paint on
`/api/system/readiness` and shows one splash with named steps (asset registry,
liquidation stream, news, model warm-up, RAG embeddings). Required steps block;
optional ones only mark the session degraded. The endpoint is pure in-memory
state — it is polled twice a second — and nothing in the startup path blocks the
socket from binding.

### 15. Public Site

Four pages sit outside the terminal, in a route group with no navigation chrome
and no boot gate — they share fonts and design tokens with the terminal and
nothing else, and three of the four render with the backend down.

* **`/` — the tour.** A scroll-driven page rendered on a single
  `position: fixed` 2D canvas. `lib/landing/stages.ts` is the one source of
  truth: each stage's height in `svh` sizes both the DOM section and the canvas
  window it maps to, so the copy and the chart it annotates cannot drift apart.
  The candle series is generated from a seed rather than `Math.random`, so the
  page draws identically on every mount.
* **`/borsa` — the BIST realm's own page, and the one exception.** A light
  Turkish document on cool paper where `/` is a dark scroll-driven scene in
  English: the thesis is that a Turkish return is read twice, so the hero figure
  physically turns over from a nominal gain into what it was worth and prints
  the division under it. It is the only marketing page that reads live data —
  BIST, the fund board, positioning and the KAP tape — so it brings its own
  `QueryClientProvider` rather than pulling the whole marketing group into the
  terminal's shell for one page, and it names its coverage where the figures
  come from.
* **`/developers` — building against it.** Eight documented sections, each with
  a generated margin figure: the provider chain, the health categories, the MCP
  tool surface, the test suites.
* **`/faq` — what it will not claim.** Eighteen deep-linkable entries on the
  limits, the data handling and the coverage, which is the part of a financial
  tool most worth writing down.
* **Every number on these pages is generated.** `lib/marketing/` holds the prose
  and is tested for one rule beyond correctness: it carries no digits. Figures
  come from `lib/generated/repo-facts.ts`, measured by the collectors described
  under [Quality Gates](#quality-gates), so a claim that stops being true fails
  CI instead of quietly ageing.
* **The tab underline lives in the layout, not the page.** A per-page header
  remounted the bar already at its destination and the transition never ran; its
  position is measured from the active tab's own box through a `ResizeObserver`,
  because the font swap changes tab widths after first paint.

---

## System Architecture

Frontend and backend are strictly decoupled: the UI never blocks on a slow
upstream, and the API never renders.

```mermaid
graph TD;
    subgraph Client [Frontend - Next.js 14 App Router]
    Landing["(marketing) - tour, borsa, developers, FAQ"]
    Gate[BootGate + readiness poll] --> UI[React Interface - 2 realms]
    UI --> Alarms[Alarm engine - client-side, 15s tick]
    UI --> RQ(React Query - server state)
    UI --> Zustand(Zustand - client state)
    UI --> Auth[Supabase Auth Context]
    end

    subgraph API [FastAPI Gateway - Python]
    Router[25 API Routers] --> Manager[Service Layer]
    Manager --> LLM[LLM provider chain]
    Manager --> RAG[(ChromaDB - RAG v1/v2)]
    Manager --> Cache[(TTL Cache + stale fallback)]
    Manager --> Sched[APScheduler Jobs]
    Manager --> Jobs[Background analysis jobs]
    Manager --> WSS[ccxt.pro Stream Fanout]
    end

    subgraph Brain [Reasoning - ordered fallback chain]
    OL[Ollama - local]
    CLOUD[Groq / Gemini / OpenAI / Anthropic / ...]
    end

    subgraph Data [Persistence]
    SB[(Supabase Postgres + RLS)]
    end

    subgraph External [External Oracles]
    CG[CoinGecko API]
    YF[Yahoo Finance]
    OKX[OKX REST + WS]
    RSS[Global RSS + Tree of Alpha]
    FG[alternative.me Fear & Greed]
    DDG[DuckDuckGo Search]
    RPC[8 chain RPC / REST endpoints]
    CM[Coin Metrics Community]
    PM[Polymarket Gamma / CLOB / Data]
    WIKI[Wikipedia electoral calendars]
    TR[TradingView scanner / TEFAS / KAP]
    TB[Takasbank SPAN + VIOP bulletin]
    RG[Resmi Gazete]
    SMTP[SMTP relay]
    end

    UI ===|REST JSON| Router
    Gate ===|/api/system/readiness| Router
    UI ===|WebSocket /ws/prices| WSS
    Alarms ===|POST /api/alarms/email/notify| Router
    Auth === SB
    Manager === SB
    Manager === External
    LLM --> OL
    LLM --> CLOUD
    Sched --> RAG

    style UI fill:#000000,stroke:#38B2AC,stroke-width:2px,color:#fff
    style Router fill:#009688,stroke:#fff,stroke-width:2px,color:#fff
    style LLM fill:#000000,stroke:#fff,stroke-width:2px,color:#fff
    style RAG fill:#FF6F00,stroke:#fff,stroke-width:2px,color:#fff
```

---

## Directory Structure

### Backend (FastAPI)

```text
backend/
├── main.py                     # ASGI factory, lifespan warm-up, CORS, GZip, router injection
├── config.py                   # pydantic-settings Settings singleton (reads backend/.env)
├── pyproject.toml              # version, ruff (line-length 100) and pytest configuration
├── requirements.txt            # runtime dependencies
├── requirements-dev.txt        # test + lint deps only — CI installs these, not torch
├── .env.example                # environment template — copy to .env
├── dependencies/
│   └── auth.py                 # bearer-token verification; the authorization boundary
├── models/
│   └── schemas.py              # Pydantic request/response models
├── prompts/                    # prompt templates as plain Markdown, {{placeholder}} syntax
│   ├── analysis/               # stage1_evidence, stage2_report, stage3_review, system_analyst
│   ├── chat/                   # system, turn, plan, plan_system, reflect, reflect_system
│   ├── chains/anomaly.md       # what co-occurring chain flags mean
│   ├── macro/regime.md         # the sentence behind the risk-on/off label
│   ├── notes/                  # rules.md (shared grounding) + seven note prompts;
│   │                           # the other three live beside their own domain:
│   │                           # asset_brief, bist_brief, bist_market,
│   │                           # bist_funds_market, bist_positioning, bist_viop,
│   │                           # kap_disclosure — the only one over a primary source
│   ├── ownership/flow.md       # last quarter's institutional moves, in prose
│   ├── polymarket/             # forecaster system, rules, arguments, synthesis,
│   │                           # synthesis_degraded, origin + six category overlays
│   └── news/ detection/ generic/
├── templates/email/            # Jinja alarm + verification mail (table layout, escaped)
├── routers/                    # 25 modules — full paths inline, no prefixes
│   ├── news.py                 # /api/news, /api/analyze, /api/symbols, /api/technical
│   ├── llm.py                  # /api/llm/status
│   ├── system.py               # /api/system/readiness, /api/system/health
│   ├── market.py               # /api/fear-greed, /api/market-overview, /api/heatmap/data
│   ├── liquidation.py          # /api/liquidations/* (heatmap, map, lines, profile,
│   │                           # levels, history), /api/market/candles
│   ├── derivatives.py          # /api/derivatives/open-interest, /dex-perps
│   ├── home.py                 # /api/home/* (funding, onchain, macro calendar)
│   ├── macro.py                # /api/macro/* (board, regime, pizza-index, neh-index,
│   │                           # elections)
│   ├── chains.py               # /api/chains/board, /api/chains/anomalies
│   ├── bist.py                 # /api/bist/* — the whole Turkish realm, 22 routes
│   ├── polymarket.py           # /api/polymarket/* (board, map, market, analysis, origin)
│   ├── alarms.py               # /api/alarms/email/* — the mail relay a browser cannot be
│   ├── watchlist.py            # /api/home/watchlist CRUD
│   ├── analysis.py             # /api/analysis/reports, /api/analysis/jobs, notes
│   ├── rag.py                  # /api/rag/* (initialize, query, insights, scenario, brief)
│   ├── chat.py                 # /api/chat, sessions, message history
│   ├── auth.py                 # session verification helpers
│   ├── profile.py              # /api/profile/* (settings, subscription, quota, BYO-key)
│   ├── community.py            # /api/community/posts, comments, likes
│   ├── social.py               # /api/social/* (sentiment, follows, public profiles)
│   ├── ownership.py            # /api/ownership/* (institutional holdings, snapshots)
│   ├── live.py                 # /api/live/* (streams, events)
│   ├── admin.py                # /api/admin/* (moderation, audit log)
│   ├── exchanges.py            # /api/exchanges, /api/multi-exchange, /api/arbitrage
│   └── websocket.py            # /ws/prices, /api/websocket/status
├── services/                   # business logic — 88 modules plus admin/, bist/,
│   │                           # chains/, community/, elections/, llm/,
│   │                           # ownership/, polymarket/ and social/ packages
│   ├── llm/                    # provider abstraction
│   │   ├── presets.py          # 14 provider rows (adapter, base_url, default model, key env)
│   │   ├── providers.py        # openai_compat / anthropic / ollama adapters
│   │   ├── client.py           # chain resolution, retries, rate-limit + daily-quota cooldowns
│   │   └── user_prefs.py       # per-user provider override resolution
│   ├── secret_box.py           # Fernet encryption for per-user API keys
│   ├── llm_settings_service.py # per-user provider/model/key persistence
│   ├── ai_service.py           # prompt assembly, response parsing, fallbacks
│   ├── prompts.py              # file-backed prompt loader ({{name}} substitution)
│   ├── prompt_budget.py        # token-ceiling context fitting
│   ├── readiness.py            # startup step tracking for the boot gate
│   ├── asset_registry.py       # live coin/stock/pair universe + disk cache + seed
│   ├── analysis_data.py        # deterministic market snapshot (no LLM)
│   ├── analysis_service.py     # four-stage market report pipeline
│   ├── analysis_jobs.py        # in-process job runner with stage progress + partials
│   ├── news_service.py         # RSS + Tree of Alpha aggregation
│   ├── article_service.py      # full-article extraction (timeout, breaker, paywall reject)
│   ├── news_analysis_service.py / news_analysis_store.py   # per-article research notes
│   ├── news_attribution.py     # persistent headline → asset memory
│   ├── symbol_detection_service.py  # LLM + registry ticker resolution
│   ├── rag_service.py          # RAG v1 — outcome memory
│   ├── rag_v2_service.py       # RAG v2 — temporal core (3 collections)
│   ├── rag_v3_service.py / rag_v4_service.py / rag_v5_service.py   # agent layer
│   ├── rag_scoring.py          # pure composite relevance/importance scoring
│   ├── rag_outcomes.py         # multi-horizon outcome measurement
│   ├── rag_bellwethers.py      # curated direction-setting asset universe
│   ├── chat_service.py         # Oracle chat orchestration (RAG + web search + LLM)
│   ├── chat_intent.py          # 13 behavioural intents; decides tools and answer rules
│   ├── chat_focus.py           # what the conversation is about, across turns
│   ├── chat_planner.py         # model-chosen tool plan from an intent-filtered catalogue
│   ├── chat_tools.py           # the tool catalogue and its executors
│   ├── chat_memory_service.py  # per-user facts that survive the session (ALLOWED_KEYS)
│   ├── ai_notes.py             # grounded note engine — facts in, one paragraph out
│   ├── macro_regime.py         # risk-on / risk-off scored in Python, explained by the model
│   ├── pentagon_pizza_service.py    # the OSINT novelty gauge, computed not copied
│   ├── finance_extractors.py   # labelled figures from table-shaped pages (TradingView, ...)
│   ├── scrape_service.py       # the fetch ladder: direct → impersonated → data → browser
│   ├── chains/                 # per-chain telemetry
│   │   ├── registry.py         # the 8 chains: protocol constants and endpoints only
│   │   ├── evm.py / bitcoin.py / solana.py / tron.py   # the four adapter families
│   │   ├── service.py          # parallel read, fee pricing, board assembly
│   │   ├── history.py          # rolling baseline, diurnally corrected
│   │   ├── anomaly.py          # what is not normal, found in Python
│   │   └── flows.py            # Coin Metrics daily exchange flow (BTC/ETH)
│   ├── polymarket/             # prediction markets
│   │   ├── gamma.py / clob.py / data_api.py   # three public APIs, two id spaces
│   │   ├── registry.py         # category tags, prompts and per-category thresholds
│   │   ├── facts.py / moves.py # model-free figures; sharp moves in probability points
│   │   ├── sufficiency.py      # the floors below which no verdict is asked for
│   │   ├── evidence.py / feeds.py / synthesis.py / attribution.py
│   │   ├── origin.py           # why this bet was opened — its own job, never chained
│   │   └── map_service.py / jurisdictions.py / geography.py   # three labelled layers
│   ├── bist/                   # Borsa İstanbul, TEFAS and the Turkish macro series
│   │   ├── tradingview_client.py / tefas_client.py   # shape adapters, nothing else
│   │   ├── equity_service.py   # the board; sectors derived from constituents
│   │   ├── heatmap_service.py  # area is cap, colour is the reader's question
│   │   ├── fund_service.py / fund_metrics.py / fund_allocation.py
│   │   ├── kap_fund_client.py / fund_holdings.py / holdings_service.py
│   │   │                       # which equities a fund holds — a monthly PDF
│   │   ├── kap_service.py      # the disclosure tape, walked page by page
│   │   ├── kap_materiality.py  # class and band on sixty rows, without a model
│   │   ├── kap_note.py         # the one note written over a primary source
│   │   ├── viop_service.py     # the in-session scrape: 19 underlyings, no history
│   │   ├── viop_bulletin.py    # the exchange's own EOD file: 47, three expiries
│   │   ├── takasbank_psr.py    # the published scan range the map's bands sit at
│   │   ├── viop_margin_map.py  # accumulate-and-sweep, but every input is read
│   │   ├── spot_volume_profile.py   # where volume actually traded — nothing modelled
│   │   ├── positioning_service.py   # crowding, quadrants, range, sector heat
│   │   ├── macro_service.py / real_return.py   # the deflators every return carries
│   │   ├── night_shift_service.py   # Gece Mesaisi — the endpoint that cannot fail
│   │   ├── sentiment_service.py / calendar_service.py
│   │   ├── brief_note.py / market_note.py / positioning_note.py / viop_note.py
│   │   ├── text.py             # Turkish folding — casefold gets İ/I wrong silently
│   │   └── gov_tls.py          # the gov hosts omit their intermediate certificate
│   ├── elections/              # wikipedia.py, odds.py, registry.py, join.py
│   ├── neh_index_service.py    # Nothing Ever Happens — recomputed, not copied
│   ├── alarm_email_service.py  # confirmation codes, HMAC tokens, per-address caps
│   ├── email_delivery.py       # smtplib in a thread; SPF/DKIM-aligned headers
│   ├── mail_settings_service.py    # admin-set SMTP, Fernet-encrypted, 0600 on disk
│   ├── email_guard.py          # MX check + disposable-domain blocklist
│   ├── ownership/flow_note.py  # last quarter's 13F moves, aggregated not recomputed
│   ├── okx_market.py           # single client for prices, candles, trades
│   ├── price_service.py        # server-side single-symbol price resolution
│   ├── liquidation_service.py  # OKX liquidation WS collector (persisted)
│   ├── liquidation_map_service.py  # modelled liquidation heatmap from free OKX data
│   ├── websocket_service.py    # ccxt.pro price stream fanout
│   ├── ccxt_service.py         # multi-exchange REST + arbitrage
│   ├── asset_detail_service.py # 30+ field aggregator for the detail modal
│   ├── market_overview_service.py / stock_market_service.py / heatmap_service.py
│   ├── fear_greed_service.py / onchain_service.py / technical_analysis_service.py
│   ├── web_search_service.py   # DuckDuckGo search for the chat agent
│   ├── supabase_service.py / profile_service.py / watchlist_service.py
│   ├── scheduler_service.py    # APScheduler: news fetch, RAG re-index, elections warm
│   ├── http_client.py          # shared async httpx client (+ impersonated transport)
│   └── cache.py                # ServiceCache (TTLCache) with stale-data fallback
├── evals/
│   ├── golden_set.jsonl        # retrieval evaluation set
│   ├── eval_planner.py         # tool-selection recall and precision
│   └── eval_refusal.py         # how often the chat declines a question it could answer
├── scripts/verify_migrations.py     # are the migrations in the repo actually live?
├── tests/                      # 124 pytest modules — run in CI
└── data/                       # local JSON state + ChromaDB stores (gitignored)
```

### Frontend (Next.js 14 App Router)

```text
frontend/
├── next.config.js              # strict mode + /api/* rewrite proxy to the backend
├── tailwind.config.ts          # UI token system, custom hex colors
├── tsconfig.json               # strict TypeScript compilation
├── vitest.config.ts            # unit test runner
├── .eslintrc.json / .prettierrc
├── .env.example                # copy to .env.local
├── app/
│   ├── layout.tsx              # fonts, tokens, metadataBase, AuthProvider, HydrationBeacon
│   ├── opengraph-image.tsx     # the link-preview card, rendered from the landing palette
│   ├── globals.css             # token definitions + terminal and landing styles
│   ├── (marketing)/            # the public site — renders with the backend down
│   │   ├── layout.tsx          # MarketingShell: header + tabs, so the underline persists
│   │   ├── page.tsx            # / — the scroll-canvas tour
│   │   ├── borsa/              # /borsa — the BIST page; the one that reads live data
│   │   ├── developers/         # /developers — eight doc sections with generated figures
│   │   ├── faq/                # /faq — eighteen deep-linkable entries
│   │   └── error.tsx           # its own boundary; (app)'s uses h-full, which is 0 here
│   └── (app)/                  # the terminal — route group, absent from the URL
│       ├── layout.tsx          # ClientShell composition
│       ├── home/               # home dashboard (/home)
│       ├── overview/           # cross-asset market matrix
│       ├── dashboard/          # news + charts + Oracle panel
│       ├── analysis/           # AI timeframe reports and notes
│       ├── chat/               # Oracle chat agent
│       ├── heatmap/            # multi-metric heatmap
│       ├── live/               # live streams and events
│       ├── derivatives/        # open interest, liquidation book and on-chain venues
│       ├── chains/             # eight-chain telemetry board
│       ├── bist/               # the Turkish realm — its own tab set, read off the path
│       │                       # hisseler/[ticker], isi-haritasi, fonlar/[kod],
│       │                       # akilli-para, kap, viop, viop-haritasi, makro, admin
│       ├── macro/              # macro calendar, regime read, elections and dashboard
│       ├── polymarket/         # prediction-market board, map and bet analysis
│       ├── ownership/          # institutional holdings
│       ├── social/             # sentiment and public profiles
│       ├── community/          # social feed and post detail
│       ├── profile/            # account, subscription, AI provider settings
│       ├── admin/              # moderation and audit
│       ├── u/[userId]/         # public user profile
│       └── auth/ error.tsx
├── components/
│   ├── ClientShell.tsx         # QueryClientProvider + Navigation + GlobalTicker + Toasts
│   ├── HydrationBeacon.tsx     # proof of life for the chunk-recovery watchdog
│   ├── BootGate.tsx / BootSplash.tsx   # holds first paint until the backend is ready
│   ├── RealmSwitcher.tsx       # global ⇄ BIST; the same control on both sides of the app
│   ├── landing/                # ScrollCanvas, TypedPoints, StageFigure, hero and sections,
│   │                           # plus the doc shell (DocPage, DocRail, FaqList, figures/)
│   ├── borsa/                  # /borsa — RealReturnHero, FlipFigure, LiveBlocks, SessionRail
│   ├── bist/                   # the Turkish realm's pages, ribbon, notes and panels,
│   │                           # plus heatmap/, positioning/ and viop/ subtrees
│   ├── ui/                     # Panel, Modal, Logo, AssetTag, ShinyText, AiNote, DataTable,
│   │                           # AssetLogo, ToggleGroup, StaleStrip, StatusMessage
│   ├── chains/                 # ChainCard, BlockStream, FeeRacer, EconomicsPanel,
│   │                           # FlowStrip, AnomalyBanner, DeviationBanner
│   ├── analysis/               # ReportView, AnalysisProgress, StageChecklist, NotesPanel,
│   │                           # TechnicalPanel, ZoneLadder, TimeframeGrid, RangeStrip
│   ├── polymarket/             # MarketCard, MarketDetail, AnalysisPanel, OriginPanel,
│   │                           # WorldMap (ECharts, dynamic — 370KB stays off first paint)
│   ├── overview/               # AdvancedHeatmap, AssetDetailModal, AssetTable,
│   │                           # MarketBreadthStrip, ChangeDistribution, DivergenceBoard
│   ├── home/                   # AssetBrief + BriefChart + LiquidityLadder, MarketRibbon,
│   │                           # FundingRates, LiquidationFeed, Watchlist, ...
│   ├── charts/                 # OpenInterestBoard, LiquidationProfile / Lines / Maps,
│   │                           # DexPerpBoard — ECharts, all dynamic
│   ├── macro/ live/ ownership/ social/ admin/ chat/
│   ├── PizzaIndexBadge.tsx     # the novelty gauge, in the nav chrome
│   ├── alarms/                 # AlarmBell in the nav chrome + the Alarm Centre dialog;
│   │                           # entirely modal, there is no /alarms route
│   ├── profile/AIProviderSettings.tsx   # BYO provider/model/API key UI
│   ├── community/              # PostCard, PostMedia, CreatePostModal
│   └── NewsFeed.tsx / ChartPanel.tsx / OraclePanel.tsx / ChatSidebar.tsx / ...
├── contexts/AuthContext.tsx    # Supabase session, signIn/signUp/signOut/OAuth
├── hooks/
│   ├── queries.ts              # React Query keys + typed hooks (optimistic mutations)
│   ├── useReadiness.ts         # /api/system/readiness poller for the boot gate
│   ├── useWebSocketPrices.ts   # /ws/prices client, reconnect + flash animation
│   ├── useAlarmEngine.ts       # global alarm watcher — one tick, twelve sources
│   └── useBist.ts              # the BIST realm's bindings, kept off `queries.ts`
├── lib/
│   ├── api.ts                  # fetch wrapper, ApiError, typed endpoint fetchers
│   ├── queryClient.ts          # QueryClient + global error → toast wiring
│   ├── supabase.ts             # lazy browser Supabase client
│   ├── chain-format.ts         # five orders of magnitude of fees in one column (tested)
│   ├── technical-format.ts     # a band is rendered as a band, never averaged (tested)
│   ├── ai-note.ts              # the shared envelope every generated note arrives in (tested)
│   ├── pizza-index.ts          # one set of thresholds for all three surfaces (tested)
│   ├── alarms/                 # what can be watched, and when it fires (tested)
│   ├── market-breadth.ts       # advance/decline, histogram, divergence (tested)
│   ├── bist-*.ts               # format, brief, heatmap, kap, viop, positioning,
│   │                           # market-note, fund-allocation, viop-map (all tested)
│   ├── night-shift.ts          # Gece Mesaisi thresholds, shared by badge and page (tested)
│   ├── nav-items.ts            # the two realms and their tab sets (tested)
│   ├── chart-palette.ts        # ECharts paints to canvas and canvas ignores var()
│   ├── open-interest.ts / liquidation-profile.ts / liquidation-lines.ts /
│   │   dex-perps.ts            # the derivatives board's derivations (tested)
│   ├── asset-brief.ts / asset-search.ts / asset-logo.ts   # the Home slots (tested)
│   ├── borsa/                  # the /borsa page's deflation arithmetic (tested)
│   ├── polymarket-format.ts    # probabilities, points, provenance labels (tested)
│   ├── elections.ts            # UTC-anchored countdowns, both sides (tested)
│   ├── marketing/              # the marketing prose — tested to carry no digits
│   ├── generated/repo-facts.ts # every number the public pages state (generated)
│   └── landing/                # scroll canvas engine — stages, series, renderer (tested)
├── assets/og/                  # subset JetBrains Mono faces for the OG image renderer
├── public/landing/             # stage imagery + CREDITS.md
└── store/useStore.ts           # Zustand global client state
```

### Repository Root

```text
.
├── start.sh / start.bat        # launchers (venv, ports, both servers, RAG seed)
├── docker-compose.yml          # production-shaped stack
├── docker-compose.override.yml # dev overrides (bind mounts, --reload, next dev)
├── supabase/migrations/        # 001_initial_schema → 014_chat_memory
├── agent-skill/                # AgentSkills for external coding agents
│   ├── oracle-x-api/           # reading a running instance
│   ├── oracle-x-dev/           # extending this codebase
│   └── *.zip                   # generated, for direct download
├── mcp-server/                 # the same API as 30 MCP tools
│   └── oracle_x_mcp/           # stdio server; talks HTTP to a live instance
├── scripts/
│   ├── build_agent_skill.py         # regenerates the skill's endpoint reference
│   ├── build_repo_facts.py          # regenerates the numbers the public pages state
│   ├── _openapi.py                  # builds the app in-process for both of the above
│   ├── calibrate_rag_relevance.py   # measures the RAG relevance floor against your store
│   ├── fetch_landing_imagery.sh     # rebuilds the landing imagery set from Wikimedia
│   └── generate_brand_assets.py
├── .github/workflows/
│   ├── ci.yml                  # ruff + compileall + pytest | lint, typecheck, test, build
│   │                           # | generated files | mcp-server
│   └── publish-packages.yml    # builds + pushes both images to ghcr.io
└── .pre-commit-config.yaml     # ruff (backend) + prettier (frontend) + hygiene hooks
```

---

## Tech Stack

### UI Layer (Next.js 14 App Router)

* **Framework:** SWC-compiled builds; server components keep client bundles
  lean.
* **Server state (React Query):** every backend read goes through
  `@tanstack/react-query` with a central key registry (`hooks/queries.ts`), 30s
  stale time, exponential-backoff retries and a global error handler that
  surfaces failures as toasts (`lib/queryClient.ts`). Mutations such as
  watchlist deletion are optimistic with automatic rollback.
* **Client state (Zustand):** the Context API re-renders the whole subtree.
  Zustand binds real-time WebSocket price updates to individual components
  without re-rendering the heatmap.
* **Styling (Tailwind CSS):** no component library — a token system and a small
  set of shared primitives in `components/ui`, for exact control over a dense
  dark interface.
* **Charting:** Apache ECharts for the data-dense panels — liquidation heatmap
  and book, open interest, treemaps, the VİOP margin map — and embedded
  TradingView widgets for classic price action. Every ECharts panel is a
  `dynamic()` import with `ssr: false`: the library is ~350 kB, which put one
  route's first load at 534 kB against 103–182 kB for every page that does not
  chart, and the palette is resolved from the live document, so a server render
  would paint the chart in fallback colours and then repaint it.

### API Engine (FastAPI, Python 3.11+)

* **Asynchronous IO:** the backend is `async def` throughout. Outbound calls
  share one configured `httpx.AsyncClient` (`services/http_client.py`); blocking
  work is dispatched to thread pools so the event loop never stalls.
* **Non-blocking startup:** uvicorn binds its socket before any warm-up runs.
  Registry priming, model loading, the first news fetch and embedding warm-up
  execute as tracked background tasks that report into `readiness`, so the boot
  gate can poll from the first second.
* **Configuration (pydantic-settings):** a cached `Settings` singleton reads
  `backend/.env`, exposing typed feature flags, intervals, provider chains and
  CORS origins, and failing fast at startup when Supabase credentials are
  absent.
* **Caching:** a `cachetools`-backed `ServiceCache` with per-service TTLs and
  stale-data fallback — if an upstream rate-limits, the last good payload is
  served instead of an error.
* **Transport realism:** a `curl_cffi` transport replays a browser TLS/HTTP2
  fingerprint for the few upstreams that fingerprint the handshake (CNN's Fear &
  Greed feed, Yahoo's chart API) and answer 418 to ordinary clients regardless
  of User-Agent. A second, narrower case sits beside it: the Turkish government
  hosts send their leaf certificate and stop, and where a browser repairs the
  chain from the leaf's AIA extension, httpx does not — so `bist/gov_tls.py`
  supplies the missing intermediate rather than disabling verification.
* **Scheduling and jobs:** `APScheduler` drives periodic news ingestion and RAG
  re-indexing; `analysis_jobs` runs the long LLM pipelines out of the request
  path with pollable stage progress.

### The Reasoning Layer

* **14 providers, one interface.** `ollama`, `groq`, `gemini`, `openai`,
  `anthropic`, `openrouter`, `deepseek`, `together`, `mistral`, `xai`,
  `cerebras`, `fireworks`, `perplexity` and `custom` (any self-hosted vLLM /
  LM Studio / LiteLLM proxy). Adding one is a row in `presets.py`, not new code,
  as long as it speaks the OpenAI chat-completions format — which nearly all of
  them do. Two adapters cover the rest: Ollama's native API, and Anthropic's
  `/v1/messages` (its OpenAI shim is documented as beta and not intended for
  production).
* **Ordered fallback chain.** `LLM_PROVIDER` names the primary and
  `LLM_FALLBACK_PROVIDERS` the chain behind it. An entry is skipped when it is
  unreachable, its key is missing, its model id is unknown, or it is still
  rate-limited after its retries.
* **Rate limits are first-class.** A 429 with a stated delay is waited out only
  if it fits `LLM_RATE_LIMIT_MAX_WAIT`; otherwise the chain moves on and that
  provider goes on cooldown, because free tiers count rejected calls against the
  same quota. A spent daily budget gets a much longer cooldown
  (`LLM_DAILY_QUOTA_COOLDOWN`), since providers report it as if it were a
  rolling minute.
* **Local-first defaults.** With `LLM_PROVIDER=ollama`, headlines, portfolios
  and chat questions never leave the machine. `qwen3.6:35b-a3b` (MoE, ~3B active
  params) is the recommended default; `qwen3.5:9b` fits lighter hardware.
  `OLLAMA_KEEP_ALIVE` keeps the model resident so a quiet period is not followed
  by a reload that times out every racing call.
* **Prompts live in files.** `backend/prompts/**.md` with `{{placeholder}}`
  substitution — reviewable and tunable without touching Python.
* **Graceful degradation.** Every LLM call has a fallback path, so the terminal
  stays usable with no provider at all: you lose AI scoring and chat, not market
  data.
* **Embeddings** run through the local Ollama daemon (`qwen3-embedding:0.6b`,
  1024-dim, multilingual), warmed at startup. The cross-encoder reranker loads
  on CUDA / MPS / CPU depending on the host.
* **The prompt is budgeted, not truncated.** Ollama cuts an over-long prompt
  from the front, and the system prompt renders first — so an overflow silently
  deletes the rules that forbid invented figures. `services/prompt_budget.py`
  fits the context to a token ceiling first, sacrificing the oldest conversation
  turns instead, and the hard constraints ride at the tail of the turn prompt
  where truncation cannot reach them.

---

## Installation

Oracle-X runs locally on macOS, Windows or a Linux server.

### Prerequisites

| Requirement | Minimum version | Notes |
|-------------|-----------------|-------|
| Node.js | v18.17.0 | Required for Next.js 14 (CI builds on v20) |
| Python | v3.11 | Matches CI |
| npm | Latest | Package management |
| Git | Latest | For cloning the repository |
| Ollama | Latest | **Optional** — only for `LLM_PROVIDER=ollama`; a cloud key works instead |

> **Hardware note:** `qwen3.6:35b-a3b` needs roughly 24 GB of free RAM/VRAM;
> `qwen3.5:9b` fits in about 7 GB. On Apple Silicon both run on the Metal
> backend out of the box. If you would rather not run a local model, set
> `LLM_PROVIDER=groq:llama-3.3-70b-versatile` (or any other supported provider)
> and skip Ollama entirely.

### Scripted setup (recommended)

`start.sh` (macOS/Linux) and `start.bat` (Windows) provision the virtualenv,
free ports 8000/3100, boot both servers, and seed the RAG index by POSTing
`/api/rag/initialize` once the API is healthy.

```bash
# 1. Clone
git clone https://github.com/Yigtwxx/OracleX.git
cd OracleX

# 2. Configure
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
# → fill in your Supabase credentials (required)
# → pick an LLM provider: keep the Ollama default, or set LLM_PROVIDER + its API key

# 3. Only if running the model locally: pull it once
ollama pull qwen3.6:35b-a3b

# 4. Start
chmod +x start.sh
./start.sh
```

On Windows, skip the `cp` and `chmod` steps — `start.bat` copies the `.env`
templates itself:

```bat
git clone https://github.com/Yigtwxx/OracleX.git
cd OracleX
ollama pull qwen3.6:35b-a3b
start.bat
```

> Windows builds its own virtualenv at `backend\venv-win\` so it never collides
> with the POSIX `backend/venv/` that `start.sh` creates. Backend and frontend
> each open in their own console window; close them to stop the services.

### Manual setup

**1. Backend**

```bash
cd backend

# start.sh expects this exact path
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env

uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Health check at `http://localhost:8000/`, Swagger UI at
`http://localhost:8000/docs`, startup progress at `/api/system/readiness`.

**2. Frontend**

```bash
cd frontend

npm install
cp .env.example .env.local

npm run dev
```

The landing page is at `http://localhost:3100`; the terminal is at
`http://localhost:3100/home`.

**3. Seed the vector memory (optional, one time)**

```bash
curl -X POST http://localhost:8000/api/rag/initialize
```

---

## Running with Docker

The whole stack is containerized. One `.env` at the repository root configures
both services.

**Prerequisites:** Docker Desktop (`brew install --cask docker-desktop` on
macOS, then open `/Applications/Docker.app` once to grant permissions).

```bash
cp .env.example .env      # then fill in the Supabase values
docker compose up --build
```

Frontend at `http://localhost:3100`, backend at `http://localhost:8000`.

### Development vs production

`docker-compose.override.yml` is loaded automatically and turns the stack into a
development environment: source is bind-mounted, uvicorn runs with `--reload`,
and the frontend runs `next dev`.

To run the production images instead — multi-stage builds, `next start` on a
standalone bundle — skip the override explicitly:

```bash
docker compose -f docker-compose.yml up --build
```

### Prebuilt images (GHCR)

Every push to `main` publishes both services to the GitHub Container Registry
(`.github/workflows/publish-packages.yml`), so a server can pull instead of
build:

```bash
docker pull ghcr.io/yigtwxx/oraclex-backend:latest
docker pull ghcr.io/yigtwxx/oraclex-frontend:latest
```

Tags: `latest` (tip of `main`), `sha-<commit>` for a pinned build, and
`<major>.<minor>` / `<version>` on `v*` tags. Point the stack at them by setting
`image:` in `docker-compose.yml` to the `ghcr.io/...` names and dropping the
`build:` block — or just run the images directly.

The published frontend image has the localhost `NEXT_PUBLIC_*` values baked in,
since they are inlined into the client bundle at build time. For a real domain,
either build the frontend yourself (see below) or set the repository variables
`NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL`, `NEXT_PUBLIC_SUPABASE_URL` and
`NEXT_PUBLIC_SUPABASE_ANON_KEY` so the workflow bakes those in instead. The
backend image takes all of its configuration at runtime, so it needs no such
treatment.

### Ollama

If you use the local provider, Ollama runs on the host, not in a container: on
Apple Silicon a containerized Ollama cannot reach the Metal GPU, which makes the
default model unusably slow. The backend is preconfigured for
`http://host.docker.internal:11434`, so once you `ollama pull <model>` on the
host it connects. Until then the backend starts normally and only logs a
warning — AI features fall through the chain or switch off. With a cloud
provider configured, none of this applies.

### Deploying to a server

Three values change together, since the browser (not the container) resolves
them:

| Variable | Local | Server |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | `https://api.yourdomain.com` |
| `NEXT_PUBLIC_WS_URL` | `ws://localhost:8000/ws/prices` | `wss://api.yourdomain.com/ws/prices` |
| `CORS_ORIGINS` | `http://localhost:3100` | `https://yourdomain.com` |

`NEXT_PUBLIC_*` values are baked into the client bundle at build time, so
changing them requires a rebuild (`docker compose build frontend`), not just a
restart.

Runtime state — Chroma vector stores, watchlists, analysis reports, liquidation
history — lives in the `backend-data` named volume and survives
`docker compose down`. Use `docker compose down -v` only when you intend to wipe
it.

The backend runs a **single uvicorn worker** by design: the APScheduler jobs,
the liquidation collector, the analysis job registry and the price-streaming
service are per-process singletons, so scaling means running one container, not
more workers.

---

## Environment Configuration

Both sides ship a committed `.env.example` — copy it rather than guessing.
Every variable has a working default except the Supabase credentials, which the
backend validates at startup and refuses to boot without. Features whose key is
missing simply switch off.

### `backend/.env`

```env
# ── Supabase (required — startup fails without these) ────────────────────────
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-publishable-anon-key
# Service-role key bypasses RLS — keep it secret, backend only.
SUPABASE_SERVICE_ROLE_KEY=your-service-role-secret-key

# ── LLM provider ─────────────────────────────────────────────────────────────
# Format: <provider> or <provider>:<model>. Only the FIRST colon splits them,
# so Ollama tags survive: ollama:qwen3.6:35b-a3b
# Supported: ollama, groq, gemini, openai, anthropic, openrouter, deepseek,
#            together, mistral, xai, cerebras, fireworks, perplexity, custom
LLM_PROVIDER=ollama
LLM_FALLBACK_PROVIDERS=            # e.g. gemini:gemini-flash-latest,ollama
LLM_MODEL=qwen3.6:35b-a3b          # used when a chain entry omits ":<model>"
LLM_MAX_RETRIES=3
LLM_RATE_LIMIT_MAX_WAIT=30         # 60 rides out a free-tier per-minute quota
LLM_RATE_LIMIT_COOLDOWN=60
LLM_DAILY_QUOTA_COOLDOWN=1800

# Encrypts per-user API keys before they reach Supabase. Empty disables the
# BYO-key feature entirely — a key is never stored in plaintext.
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
LLM_KEY_ENCRYPTION_SECRET=

# Only for LLM_PROVIDER=custom (self-hosted vLLM / LM Studio / LiteLLM proxy).
LLM_BASE_URL=
LLM_API_KEY=

# ── Local LLM (Ollama) ───────────────────────────────────────────────────────
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_KEEP_ALIVE=30m              # "-1" pins the model until the daemon stops

# ── Provider API keys — fill in only the one(s) you use ──────────────────────
GROQ_API_KEY=
GEMINI_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
OPENROUTER_API_KEY=
DEEPSEEK_API_KEY=
TOGETHER_API_KEY=
MISTRAL_API_KEY=
XAI_API_KEY=
CEREBRAS_API_KEY=
FIREWORKS_API_KEY=
PERPLEXITY_API_KEY=

# ── Optional external API keys ───────────────────────────────────────────────
ETHERSCAN_API_KEY=          # on-chain exchange flows; empty disables the feature

# Aggregated open interest for the derivatives board. Empty is fine: it falls
# back to the Binance/OKX/Bybit endpoints, shows ~30 days instead of the full
# daily series, and labels itself accordingly.
COINALYZE_API_KEY=

# ── BIST & TEFAS ─────────────────────────────────────────────────────────────
# TEFAS, KAP, Takasbank and Borsa İstanbul need no key at all. This one is the
# Turkish central bank's statistics service (EVDS), and it buys exactly one
# thing: the CPI *series*, so a real return can be computed over any window
# rather than only over the trailing year. Without it the realm still reads the
# current inflation rate, policy rate and exchange rate from the same scanner
# the equity board uses.
#
# The degradation is one-directional on purpose — a window with no deflator
# reports its nominal figure and says the real one is unavailable. It never
# borrows a nearby inflation number, because a real return computed against the
# wrong window is a specific wrong answer rather than a missing one.
TCMB_EVDS_API_KEY=

# ── Market data ──────────────────────────────────────────────────────────────
# CCXT exchange id for the live price socket. Binance is blocked in several
# countries and fails on load_markets(); any CCXT Pro venue with watch_tickers
# works — okx, bybit, kucoin, coinbase, kraken…
STREAM_EXCHANGE=okx

# ── Feature flags ────────────────────────────────────────────────────────────
USE_REAL_API=true
USE_AI=true                 # master switch for AI, whichever provider is set

# ── Chat pipeline ────────────────────────────────────────────────────────────
# Whether the model picks a turn's tools from an intent-filtered catalogue.
# Measure before turning this off again: python evals/eval_planner.py
CHAT_PLANNER_ENABLED=true
# A second, bounded look at whether the gathered evidence answers the question,
# and one chance to fix it. Separate flag on purpose — revertible independently.
CHAT_REFLECTION_ENABLED=true
# Lets the scrape ladder launch a browser for the few hosts that render entirely
# client-side. Safe to leave on with no browser installed: startup records a
# degraded health entry and the ladder reports the gap instead of failing.
# One-time install: `scrapling install`.
SCRAPLING_ALLOW_BROWSER=true
# Per-turn page-reading quotas. The browser quota stays at 1 deliberately — a
# launch costs 6-15s, which is a fifth of a turn spent on one class of evidence.
CHAT_MAX_SCRAPES_PER_TURN=3
CHAT_MAX_BROWSER_PER_TURN=1

# ── Alarm mail notifications ─────────────────────────────────────────────────
# Off by default. Leave SMTP_HOST empty and the whole panel stays hidden in the
# Alarm Centre — the toast, the sound and the OS notification all still fire.
# Any SMTP server works; Gmail needs an *app password*, not the account one.
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
# Implicit TLS from the first byte (port 465). Leave false for 587 + STARTTLS.
SMTP_SSL=false
SMTP_STARTTLS=true
SMTP_TIMEOUT=20

# Leave SMTP_FROM empty to send as SMTP_USER. That is almost always right, and
# it is what keeps mail out of the spam folder: SPF and DKIM authenticate the
# From domain, and Gmail's relay rewrites a From that is not the authenticated
# account or a verified alias.
SMTP_FROM=
SMTP_FROM_NAME=Oracle-X
SMTP_REPLY_TO=

# Signs the token a browser gets after confirming its address, and which
# POST /api/alarms/email/notify requires — without it that endpoint would be an
# open relay. One is generated and persisted if you leave this empty, so an
# admin can turn the whole feature on from the panel.
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
ALARM_EMAIL_SECRET=

ALARM_EMAIL_CODE_TTL_SECONDS=600
ALARM_EMAIL_CODE_MAX_ATTEMPTS=5
# Ceiling on notifications one confirmed address receives per hour. The failure
# this bounds is a too-loose alarm on a busy feed mailing someone until their
# provider stops trusting the sender.
ALARM_EMAIL_HOURLY_LIMIT=30

# Where the "open the terminal" button in an alarm mail points. Empty falls back
# to the first entry in CORS_ORIGINS.
APP_PUBLIC_URL=

# ── Prediction markets ───────────────────────────────────────────────────────
# No key: all three Polymarket hosts are public for reads. The URLs exist only
# so a deployment behind a mirror can redirect them.
POLYMARKET_GAMMA_URL=https://gamma-api.polymarket.com
POLYMARKET_CLOB_URL=https://clob.polymarket.com
POLYMARKET_DATA_URL=https://data-api.polymarket.com
POLYMARKET_BOARD_LIMIT=60
# The floors below which a bet analysis refuses rather than guessing, and the
# lower tier that still answers but caps its own confidence. Raising these makes
# the terminal quieter and more honest; lowering them does the reverse.
POLYMARKET_MIN_SOURCES=4
POLYMARKET_MIN_DOMAINS=3
POLYMARKET_MIN_BODY_CHARS=1200
POLYMARKET_MIN_QUERIES_ANSWERED=2
POLYMARKET_DEGRADED_MIN_SOURCES=3
POLYMARKET_DEGRADED_MIN_DOMAINS=2
POLYMARKET_DEGRADED_MIN_BODY_CHARS=600
POLYMARKET_DEGRADED_MAX_CONFIDENCE=0.45

# ── CORS (comma-separated allowed frontend origins) ──────────────────────────
CORS_ORIGINS=http://localhost:3100,http://127.0.0.1:3100

# ── Background scheduler intervals (minutes) ─────────────────────────────────
NEWS_FETCH_INTERVAL_MINUTES=2
RAG_INDEX_INTERVAL_MINUTES=30

# ── Logging (DEBUG | INFO | WARNING | ERROR) ─────────────────────────────────
LOG_LEVEL=INFO
```

RAG retrieval tuning (`RAG_MIN_RELEVANCE`, recency half-lives, importance
weights, outcome horizons) all have measured defaults in `config.py` and are
documented, commented out, in `backend/.env.example`. Re-measure the relevance
floor against your own store rather than guessing at it:

```bash
cd backend && ./venv/bin/python ../scripts/calibrate_rag_relevance.py
```

### `frontend/.env.local`

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws/prices

# Client-side auth — publishable/anon key only, never the service-role key.
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-publishable-anon-key

# Public origin this deployment is reached at. Only the link preview card needs
# it: metadataBase resolves the generated opengraph-image to an absolute URL,
# and a scraper cannot fetch a relative one.
NEXT_PUBLIC_SITE_URL=http://localhost:3100
```

### Supabase schema

Apply the migrations in `supabase/migrations/` in order, from
`001_initial_schema.sql` through `014_chat_memory.sql`, via the Supabase SQL
editor or CLI. Without them, auth-gated pages (chat history, community, profile,
ownership, per-user AI settings) will render but fail to persist.

Nothing records which files have run, so afterwards confirm the schema is
actually live rather than assuming it:

```bash
cd backend && python scripts/verify_migrations.py
```

It reads every migration, works out which tables they should leave behind
(accounting for the renames and drops later files perform), and asks the
project. Exit code 1 means a table is missing.

### Degradation matrix

| Missing | Consequence |
|---------|-------------|
| No reachable LLM provider | No AI sentiment, research notes, market reports or Oracle chat. Market data, charts and heatmaps unaffected. |
| Supabase credentials | **Backend refuses to start** — these are validated at boot. |
| `LLM_KEY_ENCRYPTION_SECRET` | Per-user BYO-key feature is disabled; the server-side provider chain still works. |
| `ETHERSCAN_API_KEY` | On-chain whale and exchange-flow widgets go empty. |
| No browser for Scrapling | Client-rendered pages (TradingView) are unreadable; the ladder names the gap and startup records a degraded health entry. Every other host is unaffected. |
| A chain RPC endpoint down | That one row on `/chains` reports `error`; the other seven report normally and the board does not 503. |
| Coin Metrics unreachable | The exchange-flow strip empties and anomaly detection falls back to its own rolling baseline. |
| `SMTP_HOST` unset | Alarm mail is off and the Alarm Centre hides its email panel. The toast, the sound and the OS notification are unaffected — mail is the fourth channel, not the only one. |
| Polymarket unreachable | `/polymarket` answers 503 rather than an empty board, and the elections panel drops its odds column and says so. |
| Thin evidence for a bet analysis | A named `insufficient_evidence` refusal listing the searches that came back empty. This is a successful run: the measured facts and microstructure above it are unaffected. |
| Wikipedia unreachable | The elections board serves its cached calendar for up to a week, then 503s — an empty board would claim no election is scheduled anywhere. |
| `TCMB_EVDS_API_KEY` unset | The BIST realm still deflates the trailing year from the scanner's own inflation reading; longer windows report their nominal figure and say the real one is unavailable. No inflation number is ever borrowed from a neighbouring window. |
| TEFAS, KAP or the BIST quote source unreachable | Only the BIST realm is affected, one board at a time, and the health badge marks `BIST & TEFAS` degraded. The global realm shares no upstream with it. |
| Takasbank's parameter file missing | `/api/bist/viop-map/{ticker}` walks back through a lookback window and renders the last published figure **with its date on the screen**; past that it 503s. The distance a band sits at is a published number and the endpoint will not substitute one. |
| Yahoo intraday history unavailable | The VİOP map loses its spot volume-profile layer and still answers. The two layers fail unequally on purpose: one is measured, the other is published. |
| Resmî Gazete unreachable | The Gece Mesaisi badge renders an `unavailable` state. The endpoint cannot fail, because it sits in the chrome of every BIST page. |
| Upstream market API down | Last good cached payload is served (stale fallback) instead of an error. |

---

## API Reference

Oracle-X is a headless data provider as well as a terminal: bots and scripts can
use the FastAPI endpoints directly without opening the UI. All payloads return
`application/json`; user-scoped routes require a Supabase bearer token.

### Market data

| Endpoint | Method | Response payload and logic |
|----------|--------|-----------------|
| `/api/market-overview` | `GET` | Global crypto market cap, dominance and top movers from CoinGecko's `/global` and `/coins/markets`. |
| `/api/nasdaq-overview` | `GET` | Live cached metrics for the "Magnificent 7" and core equities. |
| `/api/market/indices` | `GET` | Traditional index snapshots. |
| `/api/asset-detail/{symbol}` | `GET` | Resolver combining CoinGecko ID mapping and Yahoo Finance `quoteSummary`. Returns 30+ fields. |
| `/api/price/{symbol}` | `GET` | Single spot price, crypto or equity, resolved server-side. |
| `/api/market/candles/{symbol}` | `GET` | OHLCV series from OKX. |
| `/api/heatmap/data` | `GET` | Nested JSON structured for treemap consumption — price change, volume, social hype, dev activity. |
| `/api/fear-greed` | `GET` | Integer index (`0-100`) plus sentiment categorization. |
| `/api/technical/{symbol}` | `GET` | Multi-timeframe read (4h/1d/1w, or 1h/1d/1w for equities): per-horizon RSI, ATR and trend, clustered support/resistance **zones** with touch counts and strength, swing structure and alignment. Timeframes with too little history are named in `coverage` rather than faked. |

### News and AI

| Endpoint | Method | Response payload and logic |
|----------|--------|-----------------|
| `/api/news` | `GET` | Articles scored bullish/bearish/neutral with confidence and LLM-extracted tickers. |
| `/api/news/{news_id}` | `GET` | A single article by id. |
| `/api/news/{news_id}/analysis/jobs` | `POST` | Starts the staged per-article research note; joins an in-flight run for the same article. |
| `/api/news/analysis/jobs/{job_id}` | `GET` | Polls that job for its stage, partial result and final verdict. |
| `/api/news/{news_id}/analysis` | `GET` | The cached analysis, if one exists for the current pipeline version. |
| `/api/analyze` | `POST` | Runs a single article through the LLM and RAG v1 outcome memory. |
| `/api/symbols` | `GET` | Currently tracked symbol universe. |
| `/api/llm/status` | `GET` | Active provider/model, the resolved fallback chain, skipped entries and why. `?include_models=true` lists what each provider currently offers. Keys are never returned. |
| `/api/analysis/reports` | `GET` | Freshness of the stored daily/weekly/monthly reports. Never generates. |
| `/api/analysis/report/{timeframe}` | `GET` | The stored market report, or an empty one if it has not been generated yet. |
| `/api/analysis/jobs/{timeframe}` | `POST` | Starts the four-stage report pipeline in the background; joins an in-flight run for the same timeframe. |
| `/api/analysis/jobs/{job_id}` | `GET` | Polls a running report job for its stage, and its result once finished. |

### RAG and agents

| Endpoint | Method | Response payload and logic |
|----------|--------|-----------------|
| `/api/rag/initialize` | `POST` | Seeds the v2 store with historical news, events and prices. |
| `/api/rag/stats` | `GET` | Collection counts and index health. |
| `/api/rag/query` | `GET` | Semantic search across the temporal memory, composite-scored. |
| `/api/rag/news-similarity` | `POST` | Nearest historical precedents for a supplied headline. |
| `/api/rag/event-at-date` | `GET` | What the store knows happened on a given date. |
| `/api/rag/insights/{symbol}` | `GET` | v3 insights agent — why an asset moved. |
| `/api/rag/compare/{a}/{b}` | `GET` | v4 reasoning agent — two-asset comparison. |
| `/api/rag/scenario` | `POST` | v4 what-if scenario simulation. |
| `/api/rag/daily-brief` | `GET` | v5 proactive agent — morning brief. |
| `/api/rag/anomalies` | `GET` | v5 price-vs-news divergence detection. |
| `/api/chat` | `POST` | Oracle chat agent — intent classification, tool plan, evidence, reflection, answer. |
| `/api/chat/jobs` | `POST` | Runs the same turn out of the request path; `GET /api/chat/jobs/{id}` polls it and `DELETE` cancels it. |
| `/api/chat/status` | `GET` | Whether the chat agent is available, and which provider is serving it. |

### Derivatives, exchanges and real-time

| Endpoint | Method | Response payload and logic |
|----------|--------|-----------------|
| `/api/liquidations/heatmap` | `GET` | Aggregated realised-liquidation clusters from the OKX WS collector. |
| `/api/liquidations/map/{symbol}` | `GET` | Modelled liquidation map — where leveraged positions would be force-closed. |
| `/api/liquidations/levels/{symbol}` | `GET` | Per-symbol liquidation levels. |
| `/api/liquidations/history/{symbol}` | `GET` | Rolling 24h realised-liquidation history. |
| `/api/liquidations/lines/{symbol}` | `GET` | The modelled book over time — where clusters formed and how long they survived. |
| `/api/liquidations/profile/{symbol}` | `GET` | The standing book against price rather than time, binned and tiered, with spot's own bin marked. |
| `/api/derivatives/open-interest/{symbol}` | `GET` | Open interest against price per venue — the input the three liquidation views model from. Carries the aggregate change and the OI-to-market-cap ratio. |
| `/api/derivatives/dex-perps` | `GET` | On-chain perpetual venues in three independent rankings, each naming its own provider. Never joined into one table. |
| `/api/home/funding-rates` | `GET` | Perpetual funding rates across major pairs. |
| `/api/home/onchain` | `GET` | Whale transfers and exchange in/outflows. |
| `/api/home/asset-brief/{symbol}` | `GET` | One followed asset's card: price, sparkline series, the liquidity ladder around spot and a grounded sentence. |
| `/api/macro/board` | `GET` | Indices, commodities, currencies and the macro calendar in one payload. |
| `/api/macro/regime` | `GET` | The risk-on / risk-off / neutral label, its three component votes, and the model's sentence explaining them. |
| `/api/macro/pizza-index` | `GET` | Pentagon Pizza Index reading, its per-venue baselines, and the source's own figures for cross-checking. |
| `/api/macro/neh-index` | `GET` | Nothing Ever Happens index — the highest probability in a basket of tracked geopolitical markets, recomputed here from the source's raw figures. |
| `/api/macro/elections` | `GET` | Upcoming national elections with Polymarket odds joined where a market matches confidently. Carries `odds_available` and `odds_cap` so missing odds read as coverage, not as absence. |
| `/api/chains/board` | `GET` | All eight chains: height, cadence, load, priced fees, economics and recent blocks, plus the daily exchange-flow strip. A chain that could not be read carries `error` on its own row. |
| `/api/chains/anomalies` | `GET` | What on the board is not normal, each flag with a Python-written sentence, plus an hourly model note explaining why they co-occur. |
| `/api/exchanges` | `GET` | CCXT-supported exchange registry. |
| `/api/arbitrage/{base}/{quote}` | `GET` | Cross-exchange spread for a pair; `/api/arbitrage/scan` sweeps the board. |
| `/ws/prices` | `WS` | Live price stream — `snapshot` on connect, then `price_update` frames. |

### Prediction markets

| Endpoint | Method | Response payload and logic |
|----------|--------|-----------------|
| `/api/polymarket/board` | `GET` | The highest-volume open markets with prices, drift, volume and category. 503 rather than an empty board when the upstream is unreachable. |
| `/api/polymarket/map` | `GET` | The three geographic layers, each carrying its own provenance. They are never merged, because only one of them is measured. |
| `/api/polymarket/markets/{slug}` | `GET` | Model-free facts for one market: outcome prices, drift, liquidity, spread, holder concentration, microstructure notes, and the dated windows in which it re-priced. 404 for an unresolvable slug. |
| `/api/polymarket/markets/{slug}/analysis/jobs` | `POST` | Starts the bet analysis; joins an in-flight run for the same market. `GET /api/polymarket/analysis/jobs/{job_id}` polls it. May finish as an explicit `insufficient_evidence` refusal. |
| `/api/polymarket/markets/{slug}/origin/jobs` | `POST` | Starts the origin trace — why the bet was opened — as a separate job that never feeds the analysis. `GET /api/polymarket/origin/jobs/{job_id}` polls it. |

### Borsa İstanbul

The Turkish realm's surface, all under `/api/bist`. Every return in these
payloads carries its deflated counterpart beside the nominal one, and every
board names the upstream it could not reach rather than serving a shorter list.

| Endpoint | Method | Response payload and logic |
|----------|--------|-----------------|
| `/api/bist/overview` | `GET` | The realm's landing board: indices, derived sector heat, breadth and the macro strip in one payload. |
| `/api/bist/stocks` | `GET` | The equity screener — one scanner request covers the whole listing, with each company's one-year return in three frames (nominal, TÜFE-deflated, USD). |
| `/api/bist/stocks/{ticker}` | `GET` | One company: quote, fundamentals, index membership and a price history. Costs nothing the screener has not already paid for. |
| `/api/bist/heatmap` | `GET` | One index as a treemap — area is market capitalisation, colour is the reader's chosen metric, and VİOP open interest rides along where a contract exists. |
| `/api/bist/market-note` | `GET` | What the equity board says as a *set* — whether the index and the breadth agree, which no row can show. |
| `/api/bist/funds` | `GET` | The TEFAS screener: every fund the platform lists with its period returns. `/funds/compare` puts several on one axis. |
| `/api/bist/funds/{code}` | `GET` | One fund's NAV history and the risk statistics derived from it, computed against a TRY policy rate rather than against zero. |
| `/api/bist/funds/{code}/holdings` | `GET` | Which companies the fund owns, parsed from its monthly KAP portfolio report. Lazy, per fund, and written to refuse rather than guess. |
| `/api/bist/funds/market-note` | `GET` | The fund universe narrated — whether the median fund beat inflation, and how far apart the ends of the board are. |
| `/api/bist/kap` | `GET` | The disclosure tape, each row carrying a class and a materiality band computed in Python. |
| `/api/bist/kap/{index}/note` | `GET` | One filing explained — the only generated note in the codebase written over a primary source rather than over a board. |
| `/api/bist/restrictions` | `GET` | Exchange measures — circuit breakers, gross settlement, short-selling bans — filtered out of the same tape, since no feed of them exists on its own. |
| `/api/bist/viop` | `GET` | Futures and options with the open interest behind each contract: the one place in this market where positioning is published rather than inferred. |
| `/api/bist/viop-note` | `GET` | Whether the day's move was positions being opened or closed — the pairing of price and open interest, which neither column states alone. |
| `/api/bist/viop-map/underlyings` | `GET` | The single-stock futures universe, ranked by the newest session's turnover. |
| `/api/bist/viop-map/{ticker}` | `GET` | One underlying's positioning against Takasbank's published scan range, plus the observed spot volume profile. 503 without the bulletin or the parameter — the distance is a published number and this endpoint will not substitute one. |
| `/api/bist/positioning` | `GET` | Free float, unusual volume, position in the 52-week range and futures open interest. `/positioning-note` narrates what they say together. |
| `/api/bist/macro` | `GET` | Inflation, the policy rate and the exchange rate, plus the deflators the rest of the realm measures against. Answers with no key configured. |
| `/api/bist/calendar` | `GET` | Results announcements and ex-dividend dates, derived from the same scanner response the screener already paid for. |
| `/api/bist/night-shift` | `GET` | Gece Mesaisi Endeksi — how hard the state is legislating today, from the Resmî Gazete. Cannot fail: it answers `unavailable` rather than erroring, because it feeds a badge in every BIST page's chrome. |

### Alarms

Alarms themselves live in the browser; these routes exist only because a browser
cannot send mail.

| Endpoint | Method | Response payload and logic |
|----------|--------|-----------------|
| `/api/alarms/email/status` | `GET` | Whether outbound alarm mail is configured at all. |
| `/api/alarms/email/request-code` | `POST` | Sends a confirmation code, after an MX and disposable-domain check. Rate-limited. |
| `/api/alarms/email/confirm` | `POST` | Exchanges the code for an HMAC token bound to that address. |
| `/api/alarms/email/notify` | `POST` | Sends one alarm mail. Requires the token, dedupes by address and event, and caps deliveries per address per hour. 403 tells the browser to forget the address. |
| `/api/alarms/email/smtp` | `GET/PUT/DELETE` | Admin-scoped relay settings, stored encrypted outside the environment. The password is never returned — only whether one is set. `POST /api/alarms/email/smtp/test` sends a probe and passes the relay's real error through. |

### User, social and system

| Endpoint | Method | Response payload and logic |
|----------|--------|-----------------|
| `/api/system/readiness` | `GET` | Startup progress for the boot gate — per-step state, `ready`, `degraded`, `blocked`. No I/O. |
| `/api/system/health` | `GET` | The eleven upstream categories and what each last did. Passive — the HTTP helpers report what they already ran, so this is cheap enough for the frontend's ten-second poll. |
| `/api/home/watchlist` | `GET/POST/DELETE` | Watchlist CRUD with live prices merged in. |
| `/api/analysis/notes` | `GET/POST/DELETE` | Personal research notes. |
| `/api/profile` | `GET/PUT` | Profile, subscription, connected accounts, settings. Identity comes from the token. |
| `/api/profile/llm` | `GET/PUT/DELETE` | Per-user provider, model and encrypted API key. `POST /api/profile/llm/test` validates a key before saving. |
| `/api/community/posts` | `GET/POST` | Community feed; nested comment and like routes below it. |
| `/api/social/*` | `GET/POST` | Sentiment, follows and public profiles. |
| `/api/ownership/*` | `GET` | Institutional holdings boards, per-entity detail, consensus, watchlist overlap and historical snapshots. |
| `/api/ownership/flow-note` | `GET` | Last quarter's tracked-institution moves in prose, counted from filed 13F activity only. |
| `/api/admin/*` | `GET/POST` | Moderation actions and the audit log. Admin-scoped. |

### Example request

```python
import httpx

# Fetch detailed NVIDIA fundamentals from a local instance
r = httpx.get("http://localhost:8000/api/asset-detail/NVDA")
data = r.json()

print(f"Forward P/E: {data['forward_pe']}")
print(f"Target High: {data['target_high_price']}")
print(f"Analyst Rec: {data['recommendation']}")
```

### Agent skills

Two [AgentSkills](https://agentskills.io/specification) live under
[`agent-skill/`](agent-skill/), so a coding agent — Claude Code, OpenClaw, or
anything else that reads the specification — can work with Oracle-X without a
bespoke integration:

```bash
npx skills add Yigtwxx/OracleX --skill oracle-x-api    # query a running instance
npx skills add Yigtwxx/OracleX --skill oracle-x-dev    # work on this codebase
export ORACLE_X_URL=http://localhost:8000
```

One thing to know before installing: a skill has to be *consulted*, and
measurement showed `oracle-x-api` triggering on almost nothing — a model asked
"what is BTC doing" answers from its own knowledge instead of going to look.
Ask for it by name, or install it for writing code against the API, where an
agent reaches for documentation anyway. To have the numbers reach a model
unprompted, use the MCP server below.
[`agent-skill/README.md`](agent-skill/README.md) carries the measurement.

`SKILL.md` is hand-written and carries the part no generator can produce: which
endpoint answers which question, and the rules that keep an agent from
inventing a number the terminal declined to give it. The endpoint reference
beside it is generated from this app's own OpenAPI schema, and CI fails if the
committed copy has drifted from the routes:

```bash
python scripts/build_agent_skill.py --check
```

### MCP server

[`mcp-server/`](mcp-server/) exposes the same instance to any MCP client as 30
tools. Both exist on purpose. A skill has to be *consulted*, and measurement
showed the API skill triggering on almost nothing — a model asked "what is BTC
doing" answers from its own knowledge rather than going to look for a skill.
Tools are already in the model's context, so the only decision left is which
one to call.

```bash
cd mcp-server && python3.11 -m venv .venv && .venv/bin/pip install -e .
claude mcp add oracle-x -e ORACLE_X_URL=http://localhost:8000 \
  -- "$PWD/.venv/bin/python" -m oracle_x_mcp
```

Tools summarize where the raw payload is a rendering artifact: the liquidation
map answers with ~8,000 heatmap cells (214 KB), and the tool returns the
largest clusters per side anchored to spot in 1.1 KB.

---

## Quality Gates

CI (`.github/workflows/ci.yml`) runs on every push and pull request to `main`,
in four jobs:

| Job | Steps |
|-----|-------|
| **Backend** (Python 3.11) | `ruff check .` → `python -m compileall` → `pytest` |
| **Frontend** (Node 20) | `npm ci` → `npm run lint` → `npm run typecheck` → `npm test` → `npm run build` |
| **Generated files** | `python scripts/build_agent_skill.py --check` → `python scripts/build_repo_facts.py --check` |
| **MCP server** | `ruff check .` → `ruff format --check .` → `pytest` |

The backend suite is **124 pytest modules, roughly 2,700 tests** covering the LLM
chain and rate-limit behaviour, per-user settings and key encryption, auth
enforcement, prompt rendering, RAG scoring and outcomes, symbol detection, news
attribution, the analysis pipelines, chat intent/focus/memory/budget, the chain
adapters and their anomaly detection, the technical zone builder, the Polymarket
boundary and its sufficiency gate, the elections registry, alarm mail, and the
BIST realm end to end — the TEFAS and scanner shape adapters, the KAP tape and
its materiality classes, Turkish text folding, the real-return frames, the VİOP
bulletin parser and the margin map, with the Takasbank SPAN archive and the
bulletin CSV committed as fixtures so none of it reaches the network.
`requirements-dev.txt` deliberately excludes torch and chromadb so CI installs
only what the tests import.

The counts here are rounded on purpose. Exact figures live in
`frontend/lib/generated/repo-facts.ts`, measured by the collectors rather than
counted by eye, and the `--check` gate below fails the build when one stops
being true — which is how this file came to claim 1,634 backend tests long after
there were more.

A second workflow (`.github/workflows/publish-packages.yml`) is delivery, not a
gate: after a push to `main` — or a `v*` tag — it builds both Dockerfiles and
pushes them to `ghcr.io`. It never blocks a pull request.

The generated-files job rebuilds two artefacts and fails if either differs from
the committed copy. The first is the agent skill's endpoint reference, taken
from the app's OpenAPI schema: a route rename that ships an unchanged skill
produces a document describing paths the API no longer serves, and an agent
reading it cannot tell that apart from missing data. The second is
`repo-facts.ts`, the numbers the `/developers` and `/faq` pages state about this
repository. Hand-maintained they were wrong within a release and stayed wrong —
three documents claimed 26 MCP tools long after there were 30, and the frontend
suite was reported 70 tests short because someone had counted `it(` and never
saw the parametrised tables. They now come from the collectors: `pytest
--collect-only` and `vitest list` for the suites, an AST walk for the MCP tools,
the imported `CATEGORIES` and `PRESETS` for health and providers.

The frontend suite is **50 vitest modules, roughly 920 tests**, concentrated on
the pure logic where a failure would be silent rather than loud — the scroll
canvas stage schedule, the seeded candle series, the note anchors, the alarm
predicates, the market-breadth derivations, the derivatives board's binning and
venue shares, the two realms' tab sets, and the formatting rules shared between
panels (`chain-format`, `technical-format`, `ai-note`, `pizza-index`,
`polymarket-format`, and the nine `bist-*` modules). Components are deliberately
not tested; anything with a branch in it is expected to live in `lib/`.
`lib/marketing/` is tested for one extra rule: the prose carries no digits, so
every figure on a marketing page has to come from the generated facts.

`.pre-commit-config.yaml` wires the same tools locally:

```bash
pip install pre-commit && pre-commit install
pre-commit run --all-files
```

### Evals

Two behaviours are measured rather than asserted, because both fail by degrees
and neither has a right answer a unit test could pin down. They hit a live
provider, so they are run by hand and not in CI:

```bash
cd backend
python evals/eval_planner.py    # tool-selection recall and precision
python evals/eval_refusal.py    # how often chat declines a question it could answer
```

`CHAT_PLANNER_ENABLED` and the `conceptual` answer mode are both on because of
numbers these produced. Re-measure before reverting either.

### Schema drift

Migrations are applied by hand and nothing records which files have run, so the
presence of a file in `supabase/migrations/` is not evidence its schema is live
— and the failure is quiet: the backend boots, the page renders, only the write
fails.

```bash
cd backend && python scripts/verify_migrations.py
```

---

## Roadmap

Shipped in **v1.0.0**:

- [x] Dark-mode terminal layout, component system, App Router routing.
- [x] Real-time market data (CoinGecko, Yahoo Finance `quoteSummary`, OKX) with
      a TTL caching layer and stale fallback.
- [x] Semantic news pipeline, asset detail views and heatmap algorithms.
- [x] Supabase Auth with application-layer authorization — profiles, community
      feed, chat history.
- [x] ChromaDB RAG v2 temporal store, the v3/v4/v5 agent layer, and the Oracle
      chat agent with web-search augmentation.
- [x] Provider-agnostic LLM layer with fallback chains and rate-limit handling,
      per-user BYO keys encrypted at rest, file-backed prompts, staged
      report/news pipelines with job polling, calibrated RAG scoring with
      multi-horizon outcomes, and the startup boot gate.
- [x] Institutional ownership tracking, macro dashboard, live events, social
      sentiment and admin moderation with audit logging.

Shipped in **v1.1.0**:

- [x] Public landing page on a scroll-driven canvas; the terminal moves into an
      `(app)` route group.

Shipped in **v1.2.0** – **v1.3.0**:

- [x] **Chain telemetry board** — eight networks on `/chains` through four
      adapter families, comparable fees, per-row failure isolation, a
      diurnally-corrected rolling baseline and Python-computed anomaly
      detection, with Coin Metrics exchange flows for BTC and ETH.
- [x] **Chat pipeline rebuild** — intent classification, cross-turn focus,
      model-chosen tools from an intent-filtered catalogue, a bounded reflection
      round, cross-session memory (migration `014_chat_memory`), and a scrape
      ladder that can finally read charts, social posts and table-shaped pages.
      Both new behaviours ship behind their own flags, with evals attached.
- [x] **Multi-timeframe technical analysis** — three horizons per asset, support
      and resistance as clustered zones with touch counts and strength scores
      instead of drifting decimals.
- [x] **Grounded notes** — one engine writing the commentary on the macro, chain
      and ownership boards, fingerprint-cached on the facts it was given, never
      doing arithmetic.
- [x] **Macro regime read** and the **Pentagon Pizza Index** badge.
- [x] Rendered OpenGraph link-preview card, and `scripts/verify_migrations.py`
      for checking that the repo's migrations are actually live.

Unreleased (on `main`, ahead of the last tag):

- [x] **Prediction markets** — the `/polymarket` board, model-free market facts,
      sharp moves measured in probability points, an origin trace, a three-layer
      map that refuses to invent trader geography, and a bet analysis gated by
      evidence floors that is allowed to refuse rather than guess.
- [x] **Elections board** — a worldwide calendar parsed from Wikipedia, joined
      to Polymarket odds behind a two-tier confidence gate, with the calendar and
      the odds failing independently.
- [x] **Alarm Centre** — twelve watchable sources under four condition kinds,
      evaluated client-side with hysteresis and dedupe, delivered as a toast, a
      sound, an OS notification and optionally mail through an SMTP relay that
      confirms an address before it will send to it.
- [x] **Market internals** — advance/decline breadth, a fixed-bucket change
      histogram that filters the table above it, and a divergence board, all
      derived from the payload the overview already holds.
- [x] **Nothing Ever Happens index** beside the Pentagon Pizza gauge.
- [x] **Generated repository facts** — `/developers` and `/faq`, and the numbers
      on them measured by collectors and gated in CI, so a figure that stops
      being true fails the build instead of quietly ageing.
- [x] **Borsa İstanbul realm** — a second terminal on the same shell, in
      Turkish, behind a realm switcher that reads its state off the path: the
      equity screener and heatmap off one scanner request, the TEFAS fund board
      with holdings parsed out of monthly KAP portfolio PDFs, the KAP tape with
      materiality classified in Python and one filing explained by the model,
      VİOP read twice (an in-session scrape and the exchange's own end-of-day
      bulletin), positioning, and the Turkish macro backdrop. Every return is
      served with its TÜFE- and USD-deflated counterpart, because a lira figure
      alone answers a question nobody asked.
- [x] **VİOP margin map** — the crypto liquidation map with its invented
      leverage distribution replaced by Takasbank's published Price Scan Range,
      drawn beside an observed spot volume profile, and labelled as a scan range
      rather than a margin-call level because VİOP publishes no maintenance
      rate.
- [x] **Gece Mesaisi Endeksi** — the realm's counterpart to the Pentagon Pizza
      Index, read off the Resmî Gazete, on an endpoint that cannot take the
      chrome down with it.
- [x] **Derivatives board** — open interest against price, the standing
      liquidation book drawn against price rather than time, historical lines,
      and on-chain perpetual venues as three rankings that are never joined.
- [x] **Home rebuilt around what the reader follows** — three chosen slots with
      a liquidity ladder and a grounded sentence each, over a one-line market
      ribbon, in place of a screen of market-wide on-chain cards.
- [x] **`/borsa`** — a fourth public page, a light Turkish document that reads
      live figures, where the other three render with the backend down.

Planned:

- [ ] **Hardening:** contract tests over the endpoint matrix, broader component
      coverage.
- [ ] **Personalization:** migration of watchlists and notes off JSON onto
      Supabase, portfolio allocation views, saved dashboard layouts, and alarms
      that survive a change of browser.
- [ ] **v2.0 (On-chain track record):** Solidity oracles committing AI price
      impact probabilities to the Sepolia testnet for immutable track-record
      tracking.

---

## Contributing

Contributions are welcome, on the backend, the frontend or the data layer.
[CONTRIBUTING.md](CONTRIBUTING.md) covers the development setup, the coding
standards and what a reviewable pull request looks like. The short version:

1. **Fork** the repository and **branch** off `main` — `git checkout -b feat/your-feature`.
2. **Commit** using conventional commits — `git commit -m 'feat(api): add funding rate history endpoint'`.
3. **Run the gates** below.
4. **Open a pull request** targeting `main`, with screenshots for UI changes.

```bash
# Backend — the first three are CI; ruff format is enforced by pre-commit.
cd backend && ruff check . && python -m compileall -q -x "venv|data" . && pytest && ruff format --check .

# Frontend — stop the dev server first; it shares .next with the build.
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

Endpoints without test coverage should still be exercised manually against
`http://localhost:8000/docs`; note what you verified in the pull request
description.

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

---

## Security

Do not open a public issue for a vulnerability. The
[security policy](SECURITY.md) sets out what is in scope, how to report
privately, and the two deployment settings — the service-role key and
`CORS_ORIGINS` — that account for most of the real risk.

---

## License

MIT. See [LICENSE](LICENSE).
