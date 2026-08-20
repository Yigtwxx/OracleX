"""Pydantic models for API request/response schemas."""

from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime


class NewsItem(BaseModel):
    """Schema for a news item."""

    id: str
    title: str
    summary: str
    source: str
    published_at: datetime
    # None when no asset could be identified from the headline. Plenty of real
    # crypto and market news is not about a specific ticker, and attributing it
    # to one anyway would chart it against an unrelated price.
    symbol: Optional[str] = None
    asset_type: str  # "stock" or "crypto"
    url: Optional[str] = None


class AnalysisRequest(BaseModel):
    """Schema for requesting AI analysis of a news item."""

    news_id: str
    current_price: Optional[float] = None  # Current market price for technical analysis


class RsiRead(BaseModel):
    """RSI on one timeframe: the level, and which way it is going."""

    value: Optional[float] = None
    signal: Optional[str] = None
    period: int = 14
    change_5_bars: Optional[float] = None
    slope: Optional[str] = None  # rising | falling | flat
    divergence: Optional[str] = None


class TimeframeRead(BaseModel):
    """One chart of the same asset, read on its own terms."""

    timeframe: str
    horizon: str  # short | medium | long
    bars: int = 0
    covers_days: Optional[int] = None
    trend: Optional[str] = None
    atr: Optional[float] = None
    atr_percent: Optional[float] = None
    rsi: RsiRead = RsiRead()


class PriceZone(BaseModel):
    """
    A band price reversed in, not a level.

    Both bounds travel because that is what was measured; a client rendering
    only `mid` would be presenting a precision the method does not have.
    """

    low: float
    high: float
    mid: float
    touches: int = 0
    flip: bool = False
    strength: int = 0  # 0-100
    horizon: str = "medium"
    timeframe: str = ""
    timeframes: List[str] = []
    confluence: List[str] = []
    distance_percent: float = 0.0


class ChartStructure(BaseModel):
    """Where this price sits in its own multi-year history."""

    range_high: Optional[float] = None
    range_low: Optional[float] = None
    range_bars: Optional[int] = None
    range_timeframe: Optional[str] = None
    position_percent: Optional[float] = None
    distance_to_high_percent: Optional[float] = None
    distance_to_low_percent: Optional[float] = None
    sma50: Optional[float] = None
    sma200: Optional[float] = None
    price_vs_sma200_percent: Optional[float] = None
    swing_structure: Optional[str] = None
    timeframe_alignment: Optional[str] = None


class TechnicalSignals(BaseModel):
    """
    The computed chart read attached to a news analysis.

    The first four fields are the shape this model has always had, and clients
    still render them: preformatted bands, nearest first. Everything below is
    the multi-timeframe read behind them — already computed for the prompt, and
    carried here so a reader sees the same evidence the model was given rather
    than a summary of it.
    """

    rsi_signal: Optional[str] = "Neutral"
    support_levels: List[str] = []
    resistance_levels: List[str] = []
    target_price: Optional[str] = None

    current_price: Optional[float] = None
    primary_timeframe: Optional[str] = None
    timeframes: List[TimeframeRead] = []
    support_zones: List[PriceZone] = []
    resistance_zones: List[PriceZone] = []
    inside_zones: List[PriceZone] = []
    structure: Optional[ChartStructure] = None


class SentimentAnalysis(BaseModel):
    """Schema for sentiment analysis results."""

    sentiment: str  # "bullish", "bearish", "neutral"
    confidence: float  # 0.0 to 1.0
    reasoning: str
    historical_context: str
    technical_signals: Optional[TechnicalSignals] = None
    prediction_hash: Optional[str] = None
    tx_hash: Optional[str] = None
    # "keyword-fallback" when no LLM was reachable and the verdict came from a
    # word count over the headline. Absent for a real model analysis, so the UI
    # can mark the difference instead of presenting both the same way.
    source: Optional[str] = None


class PrecedentAnalogy(BaseModel):
    """
    A past event this item resembles, with what the market actually did next.

    The `surprised` / `inverted` flags are the point: an approval followed by a
    lower price, or a lawsuit followed by a higher one, is the single most
    useful thing retrieval can tell a reader — and until now it reached only the
    model, never the screen.
    """

    title: str
    date: Optional[str] = None
    symbol: Optional[str] = None
    similarity: float = 0.0
    outcome: Optional[str] = None
    price_change: Optional[float] = None
    apparent_sentiment: Optional[str] = None
    durable_direction: Optional[str] = None
    horizons: Dict[str, float] = {}
    max_drawdown_pct: Optional[float] = None
    max_runup_pct: Optional[float] = None
    surprised: bool = False
    inverted: bool = False
    source: str = "news"  # "news" | "event"


class EvidenceItem(BaseModel):
    """One claim behind the verdict, with the line that supports it."""

    claim: str
    # Verbatim from the source article. None when the point came from market or
    # regime data instead, which has no article line to quote.
    quote: Optional[str] = None
    direction: str = "neutral"  # bullish | bearish | neutral
    weight: str = "supporting"  # primary | supporting | context


class Citation(BaseModel):
    """A source the reader can open and check."""

    label: str
    url: str
    kind: str = "article"  # "article" | "corroboration"


class DataCoverage(BaseModel):
    """
    What the analysis was actually able to read.

    Always rendered, never optional: a verdict built on a headline alone must
    not look like one built on the full article and nine feeds.
    """

    article_text: str = "unavailable"  # "full" | "summary-only" | "unavailable"
    article_chars: int = 0
    unavailable: List[str] = []


class NewsAnalysis(SentimentAnalysis):
    """
    The full research note for one news item.

    Subclasses `SentimentAnalysis` so the legacy `POST /api/analyze` response
    stays byte-compatible while the job endpoints serve the richer shape.
    """

    key_factors: List[str] = []
    price_impact: Optional[str] = None
    risk_level: Optional[str] = None
    time_horizon: Optional[str] = None
    materiality: Optional[str] = None  # extraordinary|significant|routine|noise
    mechanism: Optional[str] = None
    invalidation: Optional[str] = None
    regime_note: Optional[str] = None
    evidence: List[EvidenceItem] = []
    precedents: List[PrecedentAnalogy] = []
    citations: List[Citation] = []
    coverage: DataCoverage = DataCoverage()
    analysed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    model: Optional[str] = None
    stages_run: List[str] = []


class NewsResponse(BaseModel):
    """Schema for news list response."""

    items: List[NewsItem]
    total: int


class FearGreedHistory(BaseModel):
    """Schema for Fear & Greed historical data point."""

    value: int
    classification: str
    date: str


class FearGreedData(BaseModel):
    """Schema for Fear & Greed Index response."""

    value: int  # 0-100
    classification: str  # "Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"
    timestamp: str
    history: List[FearGreedHistory] = []


class MarketStatus(BaseModel):
    """Whether the equity market is open, and what happens next."""

    status: str
    message: str
    color: str
    next_event: str = ""


class CoinData(BaseModel):
    """
    Schema for one row of the overview table — a coin or a stock.

    The optional fields are the ones only one of the two sources supplies:
    CoinGecko carries `change_7d`/`sparkline`, the NASDAQ screener carries
    `sector` and the 52-week range.

    `change_7d` is None — not 0 — when the source does not report it, because
    0 is a real reading a stablecoin posts every day. The frontend renders the
    absent case as `--` and the zero case as `+0.00%`.
    """

    symbol: str
    name: str = ""
    logo: str = ""
    price: float
    change_24h: float
    change_7d: Optional[float] = None
    sparkline: List[float] = []
    volume_24h: float
    high_24h: float
    low_24h: float
    market_cap: float = 0
    market_cap_rank: int = 0
    sector: str = ""
    fifty_two_week_high: float = 0
    fifty_two_week_low: float = 0


class MarketOverview(BaseModel):
    """
    Schema for market overview response.

    Serves both `/api/market-overview` and `/api/nasdaq-overview`; the fields
    the other market has no answer for stay at their defaults (a stock market
    has no BTC dominance, a crypto market never closes).
    """

    coins: List[CoinData]
    total_volume_24h: float
    total_market_cap: float
    btc_dominance: float
    eth_dominance: float = 0
    active_cryptocurrencies: int
    timestamp: str
    fear_greed: Optional[FearGreedData] = None
    market_status: Optional[MarketStatus] = None


class HeatmapCoin(BaseModel):
    """
    One tile on the heatmap board.

    Almost every field is optional, and that is the point: the board colours
    `>= 0` as a gain, so a missing 24h move reported as `0` renders as a green
    "+0.00%" tile — a confident claim assembled out of an absence. Each metric
    reports its own unknown and the UI draws those as an explicit no-data state.

    `sector` distinguishes three cases: None means the classification has not
    been resolved yet, "Other" means it was resolved and matched nothing, and
    anything else is a real sector.
    """

    id: str
    symbol: str
    name: str
    image: str = ""
    sector: Optional[str] = None
    # "stablecoin" | "wrapped" | None — an asset tracking another price rather
    # than finding its own. Hidden from the board by default: a USDT tile reads
    # a flat 0.00% every day and tells the viewer nothing about the market.
    peg_type: Optional[str] = None
    price: Optional[float] = None
    market_cap: float = 0
    volume_24h: Optional[float] = None
    price_change_24h: Optional[float] = None
    price_change_7d: Optional[float] = None
    # 0-100, log-scaled against absolute dollar volume ($1M -> 0, $100B -> 100).
    volume_score: Optional[float] = None
    turnover_pct: Optional[float] = None
    developer_score: Optional[float] = None


class HeatmapSector(BaseModel):
    """
    A sector's aggregate, weighted by market cap.

    `weighted_change_24h` is the honest figure: an unweighted mean lets a $300M
    token move the sector as much as a $2T one. `avg_change_24h` is the old
    unweighted mean, kept while the generated report migrates off it.

    `coverage` is the share of the sector's coins that actually had a reading,
    so a sector aggregated from two of its eleven members can say so instead of
    presenting that as the sector's return.
    """

    sector: str
    coin_count: int
    market_cap: float = 0
    weighted_change_24h: Optional[float] = None
    weighted_change_7d: Optional[float] = None
    avg_change_24h: Optional[float] = None
    coverage: float = 0
    coins: List[HeatmapCoin] = []


class HeatmapData(BaseModel):
    """
    The heatmap board.

    Never empty on success — when the board genuinely cannot be produced the
    endpoint answers 503 rather than an empty `coins` list, because a blank
    grid served with a 200 is indistinguishable from a market where nothing is
    listed.

    `stale` and `age_seconds` mark a board served from the last known good copy
    after a failed refresh. That is a better answer than an error page, but only
    if the client can say so.
    """

    coins: List[HeatmapCoin]
    sectors: List[HeatmapSector]
    total_market_cap: float = 0
    weighted_change_24h: Optional[float] = None
    weighted_change_7d: Optional[float] = None
    # Pegged assets filtered out of this board; surfaced so the UI can offer to
    # show them rather than silently dropping rows.
    excluded_pegged: int = 0
    # Coins still waiting on their first successful detail request.
    unresolved_count: int = 0
    timestamp: str
    stale: bool = False
    age_seconds: Optional[float] = None
