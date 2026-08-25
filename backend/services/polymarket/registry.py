"""
Polymarket's endpoints, and the per-category research strategy.

Everything here is either an address or a policy. Anything that can differ
between two polls — a price, a volume, a holder — is measured by the adapters
and never stored here, the same rule `services/chains/registry.py` runs on.

The strategy table is the load-bearing part. A market asking whether a coalition
will collapse and one asking whether Bitcoin closes above a level are not
answered by the same wires, the same search phrasing, or the same standard of
proof, and the alternative to writing that down once is scattering six special
cases through the sweep. Keeping it in one frozen table is also what keeps the
sufficiency rule auditable: every threshold override in the product is visible
on this page.

`prompt` is a plain string literal on purpose. `tests/test_prompts.py` scans the
source for literal template names, so an f-string here would make all six
category overlays read as templates nobody references — a failing test and, more
to the point, a real hazard, since a renamed overlay would then go unnoticed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── Upstream addresses ───────────────────────────────────────────────────────
# Three hosts, all public and unauthenticated for reads. They are split by role
# rather than by convenience: Gamma knows what markets exist, CLOB knows what
# they cost, and the data API knows who traded them. Only Gamma is required —
# a market with no metadata cannot be rendered at all, while a missing holder
# table is a named gap.
GAMMA_MARKETS = "/markets"
GAMMA_EVENTS = "/events"
CLOB_PRICES_HISTORY = "/prices-history"
CLOB_BOOK = "/book"
DATA_HOLDERS = "/holders"
DATA_TRADES = "/trades"

# Per-call budgets. Deliberately below the stage budget that contains them, so a
# single slow upstream is a named gap rather than a lost stage.
METADATA_TIMEOUT = 10.0
HISTORY_TIMEOUT = 10.0
HOLDERS_TIMEOUT = 8.0
TRADES_TIMEOUT = 8.0

# The CLOB history granularity the move detector assumes. One hour is the
# coarsest resolution at which a six-hour window still has six samples in it;
# finer than this and a market that ticks all day drowns the detector in
# candidates it then has to throw away.
HISTORY_FIDELITY_MINUTES = 60


@dataclass(frozen=True)
class CategoryStrategy:
    """How a market of one kind gets researched, and what counts as enough."""

    key: str
    label: str
    #: Template name for the category overlay. A literal — see module docstring.
    prompt: str
    #: `{subject}` is the market's noun phrase, `{year}` the resolution year.
    query_templates: tuple[str, ...]
    #: At most four. Each one costs a round trip inside the sweep budget.
    feeds: tuple[tuple[str, str], ...]
    #: Outlets whose body text counts as tier 1. Not a quality ranking so much
    #: as a corroboration one: these are the desks that get corrected in public.
    preferred_domains: frozenset[str]
    rag_enabled: bool = False
    rag_asset_type: str | None = None
    #: None means "inherit the configured floor". A number here is a real
    #: override and the only place one may live, which is what keeps the
    #: sufficiency rule auditable from a single page. Writing the global default
    #: out again in every strategy would make the config setting decorative for
    #: whichever categories happened to restate it.
    min_sources: int | None = None
    min_tier1: int = 1
    scrape_budget: int = 3
    keywords: tuple[tuple[str, float], ...] = field(default_factory=tuple)


_WIRE_AP = ("AP", "https://feeds.apnews.com/rss/apf-topnews")
_WIRE_BBC = ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml")
_WIRE_MARKETWATCH = (
    "MarketWatch",
    "https://feeds.content.dowjones.io/public/rss/mw_topstories",
)

STRATEGIES: tuple[CategoryStrategy, ...] = (
    CategoryStrategy(
        key="politics",
        label="Politics",
        prompt="polymarket/category_politics",
        query_templates=(
            "{subject} latest polling",
            "{subject} news {year}",
            "{subject} analysis odds",
        ),
        feeds=(
            ("NPR Politics", "https://feeds.npr.org/1014/rss.xml"),
            ("The Hill", "https://thehill.com/homenews/feed/"),
            _WIRE_AP,
        ),
        preferred_domains=frozenset(
            {
                "apnews.com",
                "npr.org",
                "thehill.com",
                "politico.com",
                "reuters.com",
                "nytimes.com",
                "wsj.com",
                "bbc.com",
            }
        ),
        keywords=(
            ("election", 2.0),
            ("president", 1.5),
            ("senate", 1.5),
            ("congress", 1.5),
            ("parliament", 1.5),
            ("nominee", 1.5),
            ("primary", 1.0),
            ("vote", 1.0),
            ("candidate", 1.0),
            ("impeach", 1.5),
            ("cabinet", 1.0),
            ("coalition", 1.0),
            ("prime minister", 2.0),
            ("referendum", 2.0),
            ("chancellor", 1.5),
            ("governor", 1.0),
        ),
    ),
    CategoryStrategy(
        key="geopolitics",
        label="Geopolitics",
        prompt="polymarket/category_geopolitics",
        query_templates=(
            "{subject} latest developments",
            "{subject} news {year}",
            "{subject} ceasefire OR sanctions OR talks",
        ),
        feeds=(
            _WIRE_BBC,
            ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
            _WIRE_AP,
        ),
        preferred_domains=frozenset(
            {
                "bbc.com",
                "bbc.co.uk",
                "aljazeera.com",
                "reuters.com",
                "apnews.com",
                "ft.com",
                "economist.com",
                "nytimes.com",
            }
        ),
        keywords=(
            ("war", 2.0),
            ("ceasefire", 2.0),
            ("invasion", 2.0),
            ("invade", 2.0),
            ("annex", 2.0),
            ("hostage", 2.0),
            ("airstrike", 2.0),
            ("blockade", 2.0),
            ("coup", 2.0),
            ("sanction", 1.5),
            ("nato", 1.5),
            ("military", 1.5),
            ("treaty", 1.5),
            ("nuclear", 1.5),
            ("missile", 1.5),
            ("troops", 1.5),
            ("strike", 1.0),
            ("border", 1.0),
        ),
    ),
    CategoryStrategy(
        key="macro",
        label="Macro",
        prompt="polymarket/category_macro",
        query_templates=(
            "{subject} forecast {year}",
            "{subject} economists expect",
            "{subject} data release",
        ),
        feeds=(
            _WIRE_MARKETWATCH,
            ("Investing.com", "https://www.investing.com/rss/news.rss"),
        ),
        preferred_domains=frozenset(
            {
                "reuters.com",
                "bloomberg.com",
                "wsj.com",
                "ft.com",
                "cnbc.com",
                "marketwatch.com",
                "federalreserve.gov",
                "bls.gov",
            }
        ),
        rag_enabled=True,
        rag_asset_type="stock",
        keywords=(
            ("inflation", 2.0),
            ("cpi", 2.0),
            ("fed", 2.0),
            ("interest rate", 2.0),
            ("recession", 2.0),
            ("gdp", 1.5),
            ("unemployment", 1.5),
            ("tariff", 1.5),
            ("oil price", 1.5),
            ("jobs report", 1.5),
        ),
    ),
    CategoryStrategy(
        key="crypto",
        label="Crypto",
        prompt="polymarket/category_crypto",
        query_templates=(
            "{subject} price prediction {year}",
            "{subject} news",
            "{subject} regulation OR approval",
        ),
        feeds=(
            ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss"),
            ("The Block", "https://www.theblock.co/rss.xml"),
            ("Decrypt", "https://decrypt.co/feed"),
        ),
        preferred_domains=frozenset(
            {
                "coindesk.com",
                "theblock.co",
                "decrypt.co",
                "cointelegraph.com",
                "sec.gov",
                "reuters.com",
                "bloomberg.com",
            }
        ),
        rag_enabled=True,
        rag_asset_type="crypto",
        keywords=(
            ("bitcoin", 2.0),
            ("ethereum", 2.0),
            ("crypto", 1.5),
            ("token", 1.0),
            ("etf", 1.5),
            ("solana", 1.5),
            ("stablecoin", 1.5),
            ("halving", 1.5),
            ("blockchain", 1.0),
        ),
    ),
    CategoryStrategy(
        key="sports",
        label="Sports",
        prompt="polymarket/category_sports",
        query_templates=(
            "{subject} preview odds",
            "{subject} injury report news",
        ),
        feeds=(
            ("ESPN", "https://www.espn.com/espn/rss/news"),
            ("BBC Sport", "https://feeds.bbci.co.uk/sport/rss.xml"),
        ),
        preferred_domains=frozenset(
            {"espn.com", "bbc.com", "bbc.co.uk", "theathletic.com", "skysports.com"}
        ),
        # Sport is the one category where the primary record is a scoreline and
        # a team sheet rather than prose, so demanding a scraped body from a
        # named desk would refuse markets that are in fact well covered. The
        # floor moves; it does not disappear.
        min_sources=3,
        min_tier1=0,
        keywords=(
            ("nba", 2.0),
            ("nfl", 2.0),
            ("premier league", 2.0),
            ("champions league", 2.0),
            ("world cup", 2.0),
            ("match", 1.0),
            ("season", 1.0),
            ("playoff", 1.5),
            ("tournament", 1.0),
        ),
    ),
    CategoryStrategy(
        key="general",
        label="General",
        prompt="polymarket/category_general",
        query_templates=(
            "{subject} news {year}",
            "{subject} latest",
        ),
        feeds=(_WIRE_BBC, _WIRE_MARKETWATCH),
        preferred_domains=frozenset({"reuters.com", "apnews.com", "bbc.com", "bbc.co.uk"}),
    ),
)

STRATEGY_BY_KEY: dict[str, CategoryStrategy] = {s.key: s for s in STRATEGIES}

# Gamma tag slugs that settle a market's category outright, checked before any
# keyword scoring. These are real slugs, counted over ~400 live markets rather
# than guessed: Gamma publishes 232 distinct tags and most of them are market
# mechanics ("recurring", "hit-price", "earn-4") rather than subjects, so an
# allowlist is the only workable shape. Tags are only present when the market
# was fetched with `include_tag=true` — without it this pass never fires and
# everything falls through to keywords.
#
# Ordered by specificity, first match wins. Geopolitics leads because its
# markets are almost always tagged "politics" as well, and a war is not
# researched off the desks that cover primaries. Politics sits last for the same
# reason in reverse: it is the broadest tag Polymarket applies.
TAG_PRIORITY: tuple[tuple[str, str], ...] = (
    # Geopolitics — conflict, diplomacy and the chokepoints between them.
    ("geopolitics", "geopolitics"),
    ("macro-geopolitics", "geopolitics"),
    ("world-affairs", "geopolitics"),
    ("military-strikes", "geopolitics"),
    ("peace-deal", "geopolitics"),
    ("diplomacy-ceasefire", "geopolitics"),
    ("strait-of-hormuz", "geopolitics"),
    ("blockade", "geopolitics"),
    ("israel-x-iran", "geopolitics"),
    ("trump-iran", "geopolitics"),
    ("middle-east", "geopolitics"),
    ("iran", "geopolitics"),
    ("israel", "geopolitics"),
    ("ukraine", "geopolitics"),
    ("russia", "geopolitics"),
    ("putin", "geopolitics"),
    # Crypto.
    ("crypto", "crypto"),
    ("crypto-prices", "crypto"),
    ("bitcoin", "crypto"),
    ("ethereum", "crypto"),
    ("xrp", "crypto"),
    ("ripple", "crypto"),
    ("solana", "crypto"),
    # Sport, including esports — the closest strategy there is, and closer than
    # the general wires would be.
    ("sports", "sports"),
    ("esports", "sports"),
    ("games", "sports"),
    ("soccer", "sports"),
    ("football", "sports"),
    ("nfl", "sports"),
    ("nba", "sports"),
    ("super-bowl", "sports"),
    ("tennis", "sports"),
    ("atp", "sports"),
    ("league-of-legends", "sports"),
    ("counter-strike-2", "sports"),
    ("dota-2", "sports"),
    # Macro.
    ("economy", "macro"),
    ("finance", "macro"),
    ("finance-updown", "macro"),
    ("oil", "macro"),
    ("commodities", "macro"),
    ("inflation", "macro"),
    ("fed", "macro"),
    # Politics, last and broadest.
    ("politics", "politics"),
    ("elections", "politics"),
    ("global-elections", "politics"),
    ("world-elections", "politics"),
    ("us-presidential-election", "politics"),
    ("main-election", "politics"),
    ("primaries", "politics"),
    ("international-election-props", "politics"),
    ("president", "politics"),
    ("trump", "politics"),
)


def strategy_for(category: str) -> CategoryStrategy:
    """The research strategy for a category, falling back to `general`."""
    return STRATEGY_BY_KEY.get(category, STRATEGY_BY_KEY["general"])
