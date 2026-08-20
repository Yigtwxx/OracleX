"""
What a chat turn is actually being asked for.

Until now the only thing a turn understood about a question was which asset it
named. Everything else was decided by keyword tables scattered across
`chat_tools` — one for scenarios, one for comparisons, one for "why" questions,
three more for which snapshot sections to pull. Each table was consulted at a
different point by a different caller, and no single value said what kind of
question this was.

That gap is what made conceptual questions unanswerable. "What is a funding
rate" resolves no asset, so no asset tool is offered, so no evidence block is
built — and the turn prompt's standing rule is that every figure must appear in
the context. The model then correctly concludes it has nothing admissible to say
about a question that needed no market data in the first place.

So the intent is computed once, early, in pure Python, and it drives two things:
which tools are worth offering, and which rules the answer is held to.

**This module makes no LLM call and imports nothing from `chat_tools`.** The
dependency runs the other way — `chat_tools` imports the keyword tables from
here — because a classifier that needed the tool registry could not be used to
decide what the tool registry should offer.

The LLM planner returns an intent too, and it is better at the ambiguous cases.
It does not replace this one: the planner can be switched off, time out, or
return garbage, and the answer's rule block cannot be allowed to depend on that.
`coerce` is where the planner's label is let back in.
"""

import re
from typing import Optional, Tuple

# ═══════════════════════════════════════════════════════════════════════════════
# THE TAXONOMY
# ═══════════════════════════════════════════════════════════════════════════════

# Deliberately small and behavioural. Each name exists because it changes either
# which tools are offered or which rules the answer is held to; a distinction
# that changes neither does not earn a row.
INTENTS: Tuple[str, ...] = (
    "conceptual",  # how does X work — needs no market data
    "current_state",  # how is X doing — the default for an asset question
    "causal",  # why did X move
    "comparative",  # X versus Y
    "scenario",  # what if X happens
    "news",  # what happened / what is being said
    "macro",  # rates, dollar, commodities, regime
    "derivatives",  # funding, open interest, liquidations
    "ownership",  # institutional holders, 13F, insider flow
    "portfolio",  # the user's own list or positions
    "briefing",  # what did I miss
    "greeting",  # hello, thanks, ok
    "offtopic",  # not about markets at all
)

DEFAULT_INTENT = "current_state"

# Intents that describe something other than the present state of an asset, and
# therefore must not inherit an asset from an earlier turn. "What is a funding
# rate" asked after three questions about BTC is still not a question about BTC.
FOCUS_CLEARING_INTENTS = frozenset({"conceptual", "greeting", "offtopic", "macro", "briefing"})

# ═══════════════════════════════════════════════════════════════════════════════
# MARKERS
# ═══════════════════════════════════════════════════════════════════════════════

# Turkish and English side by side throughout, because the product is used in
# both and a table that covers one is a feature that works for half the users.

# The new one, and the one the "cannot answer" complaint hinges on. Matched as
# regexes rather than substrings so "nedir" does not fire on "nedirse" and
# "what is" can tolerate the words between it and its object.
CONCEPTUAL_PATTERNS = (
    r"\bnedir\b",
    r"\bne demek\b",
    r"\bne i̇?şe yarar\b",
    r"\bnas[ıi]l çal[ıi]ş",
    r"\bnas[ıi]l hesapla",
    r"\bnas[ıi]l tan[ıi]mlan",
    r"\bnas[ıi]l okun",
    r"\baçıkla",
    r"\bfark[ıi]? ne",
    r"\bne anlama gel",
    r"\bwhat (?:is|are)\b",
    r"\bwhat does .{0,40}\bmean\b",
    r"\bhow (?:do|does|is|are) .{0,40}\b(?:work|calculated|defined|computed)\b",
    r"\bexplain\b",
    r"\bdefine\b",
    r"\bdifference between\b",
)

# A conceptual phrasing that also points at now is a question about now:
# "what is BTC doing right now" is not a definition request.
PRESENT_MARKERS = (
    "şu an",
    "şu anda",
    "bugün",
    "şimdi",
    "right now",
    "currently",
    "at the moment",
    "today",
    "as of now",
)

# Turkish is agglutinative, so a greeting is a stem plus whatever the speaker
# suffixed onto it: "teşekkürler", "sağolun", "tamamdır". The `\w*` is what
# stops the word boundary from landing mid-suffix and failing the match — the
# English entries keep a bare boundary because "ty" and "ok" must not fire on
# "type" and "okra".
GREETING_CLAUSES = (
    r"selam\w*",
    r"merhaba\w*",
    r"s\.?a\.?",
    r"günayd[ıi]n\w*",
    r"iyi ak[şs]amlar",
    r"nas[ıi]ls[ıi]n\w*",
    r"ne haber",
    r"te[şs]ekk[üu]r\w*",
    r"sa[ğg] ?ol\w*",
    r"eyvallah",
    r"tamam\w*",
    r"hey",
    r"hi",
    r"hello",
    r"yo",
    r"thanks",
    r"thank you",
    r"how are you",
    r"ty",
    r"ok(?:ay)?",
)

SCENARIO_KEYWORDS = (
    "what if",
    "scenario",
    "suppose",
    "what would happen",
    "eğer",
    "olursa",
    "senaryo",
    "farz edelim",
    "diyelim ki",
)

COMPARISON_KEYWORDS = (
    " vs ",
    " vs. ",
    "versus",
    "compare",
    "karşılaştır",
    "kıyasla",
    "hangisi daha",
    "which is better",
)

WHY_KEYWORDS = (
    "why",
    "reason",
    "what happened",
    "what's driving",
    "whats driving",
    "what is driving",
    "neden",
    "niye",
    "niçin",
    "sebebi",
    "ne oldu",
)

# Questions about what people are saying, as opposed to what happened. The
# distinction matters because anonymous chatter is the least reliable evidence a
# turn can gather, so it is worth offering only when it is what was asked for.
SOCIAL_KEYWORDS = (
    "sentiment",
    "people saying",
    "what are people",
    "chatter",
    "reddit",
    "twitter",
    "stocktwits",
    "crypto twitter",
    "community",
    "ne diyorlar",
    "yorumlar",
    "sosyal",
    "kamuoyu",
    "millet ne",
)

NEWS_KEYWORDS = (
    "news",
    "headline",
    "announced",
    "announcement",
    "statement",
    "said",
    "haber",
    "duyuru",
    "açıklama",
    "dedi",
    "gelişme",
    "son dakika",
)

BRIEFING_KEYWORDS = (
    "what did i miss",
    "catch me up",
    "anything interesting",
    "ne kaçırdım",
    "neler oldu",
    "özetle",
    "brifing",
    "günlük özet",
    "bugün ne var",
)

OWNERSHIP_KEYWORDS = (
    "13f",
    "form 4",
    "insider",
    "institutional",
    "hedge fund",
    # "holder" alone missed "who holds NVDA", which is how the question is
    # actually asked. The inflections are listed rather than stemmed to "hold",
    # which also matched "hold on a second".
    "holds",
    "holder",
    "holding",
    "who owns",
    "ownership",
    "stake",
    "asset manager",
    "kurumsal",
    "içeriden",
    "hissedar",
    "kim tutuyor",
    "sahiplik",
    "fon",
)

PORTFOLIO_KEYWORDS = (
    "my watchlist",
    "my portfolio",
    "my positions",
    "izleme listem",
    "portföyüm",
    "pozisyonum",
    "listemdeki",
)

# Kept in sync with what `chat_tools.snapshot_sections` pulls: a question that
# earns the derivatives section is a question the derivatives intent describes.
DERIVATIVES_KEYWORDS = (
    "liquidat",
    "funding",
    "leverage",
    "open interest",
    "futures",
    "perp",
    "derivative",
    "whale",
    "long squeeze",
    "short squeeze",
    "likidasyon",
    "kaldıraç",
    "açık pozisyon",
)

SECTOR_KEYWORDS = ("sector", "rotation", "defi", "meme", "layer 1", "layer 2", "narrative")

# The commodity board answers the risk-on/risk-off question, which is asked
# about the dollar and gold far more often than about wheat — but "commodity"
# and the specific contracts have to be here too, or the question that names
# one gets an answer built without it.
MACRO_KEYWORDS = (
    "dollar",
    "dxy",
    "gold",
    "silver",
    "copper",
    "oil",
    "crude",
    "brent",
    "gas",
    "commodit",
    "macro",
    "inflation",
    "risk-on",
    "risk-off",
    "fed",
    "fomc",
    "rate cut",
    "rate hike",
    "cpi",
    "dolar",
    "altın",
    "gümüş",
    "petrol",
    "emtia",
    "makro",
    "enflasyon",
    "faiz",
)

# Questions that are about the market in general rather than about whatever
# asset the previous turn was about. Used by `chat_focus` to decide that an
# inherited symbol should be dropped.
MARKET_WIDE_MARKERS = (
    "the market",
    "markets",
    "overall",
    "in general",
    "altcoins",
    "altcoin season",
    "breadth",
    "piyasa",
    "piyasalar",
    "genel olarak",
    "genelde",
    "altcoinler",
)

# Openers that continue the previous subject rather than replacing it.
# "peki ETH?" adds to the focus; "ETH nasıl?" replaces it.
ADDITIVE_PATTERNS = (
    r"^(?:peki|ya|ve|bir de|birde|ayrıca)\b",
    r"^(?:and|also|what about|how about|plus)\b",
)

# The word→enum map for candle timeframes. It lives here rather than only in
# `prompts/chat/plan_system.md` so the prompt's table and the code that reads a
# timeframe off a message cannot drift apart. The prompt still documents it for
# the planner; this is what the deterministic path uses.
TIMEFRAME_WORDS = {
    "15m": ("15 minute", "15m", "15 dk", "15dk", "çeyrek saat", "quarter-hourly"),
    "1h": ("1 hour", "1h", "hourly", "1 saatlik", "saatlik", "bir saatlik"),
    "4h": ("4 hour", "4h", "4 saatlik", "dört saatlik", "intraday"),
    "1d": ("daily", "1d", "günlük", "gunluk", "day chart"),
    "1w": ("weekly", "1w", "haftalık", "haftalik", "week chart"),
}

_CONCEPTUAL_RE = re.compile("|".join(CONCEPTUAL_PATTERNS), re.IGNORECASE)
_GREETING_CLAUSE_RE = re.compile(r"^(?:" + "|".join(GREETING_CLAUSES) + r")$", re.IGNORECASE)
# Clause separators. A greeting is allowed to be several of them — "selam,
# nasılsın" — but every part has to be one.
_CLAUSE_SPLIT_RE = re.compile(r"[,;!.?]+")
_ADDITIVE_RE = re.compile("|".join(ADDITIVE_PATTERNS), re.IGNORECASE)


def _is_greeting(lowered: str) -> bool:
    """
    Whether the message is *only* a greeting.

    Matching a greeting at the start was the obvious rule and the wrong one:
    "teşekkürler, peki neden BTC düştü" opens with an acknowledgement and is a
    causal question. So every clause has to be a greeting, not just the first.
    """
    clauses = [c.strip() for c in _CLAUSE_SPLIT_RE.split(lowered)]
    clauses = [c for c in clauses if c]
    if not clauses:
        return False
    return all(_GREETING_CLAUSE_RE.match(c) for c in clauses)


# ═══════════════════════════════════════════════════════════════════════════════
# CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════════════


def _has(message: str, keywords: Tuple[str, ...]) -> bool:
    return any(keyword in message for keyword in keywords)


def classify(message: str, symbol_count: int = 0) -> str:
    """
    What kind of question this is, from the message alone.

    `symbol_count` is how many assets the message resolved to; it only breaks
    the tie between "comparative" and everything else, because a comparison
    needs two things to compare and a message that names one is asking
    something else regardless of how it is phrased.

    Order is precedence, and it is the whole design. A question can carry
    markers from several rows — "why is funding so high right now" is causal and
    derivatives and present-tense — so the rows are ordered by which reading
    changes the answer most. Conceptual comes near the top because getting it
    wrong is the failure this module exists to fix; `current_state` is last
    because it is the default a market question falls back to.
    """
    lowered = (message or "").strip().lower()
    if not lowered:
        return "greeting"

    # 1. Greetings and acknowledgements, and only when that is all there is.
    if _is_greeting(lowered):
        return "greeting"

    # 2. Definitional. Gated on the absence of a present-tense marker, so
    #    "what is BTC doing right now" stays a question about now.
    if _CONCEPTUAL_RE.search(lowered) and not _has(lowered, PRESENT_MARKERS):
        return "conceptual"

    # 3. Hypotheticals. Checked before the topical rows because "what if the ETF
    #    is denied" is a scenario question that happens to mention news.
    if _has(lowered, SCENARIO_KEYWORDS):
        return "scenario"

    # 4. Comparisons need two assets. Phrasing alone is not enough: "compare it
    #    to last month" is one asset over time, which is not this tool's job.
    if _has(lowered, COMPARISON_KEYWORDS) and symbol_count >= 2:
        return "comparative"

    # 5. The user's own list, before the topical rows — "how is my watchlist
    #    doing" is a portfolio question that reads like a state question.
    if _has(lowered, PORTFOLIO_KEYWORDS):
        return "portfolio"

    if _has(lowered, BRIEFING_KEYWORDS):
        return "briefing"

    # 6. Causality outranks the topical rows: "why did funding spike" wants an
    #    explanation, and the derivatives data is the evidence for it, not the
    #    answer to it.
    if _has(lowered, WHY_KEYWORDS):
        return "causal"

    if _has(lowered, OWNERSHIP_KEYWORDS):
        return "ownership"

    if _has(lowered, DERIVATIVES_KEYWORDS):
        return "derivatives"

    # 7. Macro only when no asset was named. "How is gold affecting BTC" names
    #    an asset and is a question about that asset's backdrop, which
    #    `current_state` already pulls the macro section for.
    if _has(lowered, MACRO_KEYWORDS) and symbol_count == 0:
        return "macro"

    if _has(lowered, NEWS_KEYWORDS):
        return "news"

    return DEFAULT_INTENT


def coerce(raw: Optional[str]) -> Optional[str]:
    """
    A model-supplied intent label, or None if it is not one we know.

    Returning None rather than a default is deliberate: the caller already has a
    deterministic classification and should keep it, rather than have it
    replaced by a fallback that carries no information.
    """
    if not isinstance(raw, str):
        return None
    candidate = re.sub(r"[^a-z_]+", "_", raw.strip().lower()).strip("_")
    return candidate if candidate in INTENTS else None


def is_additive(message: str) -> bool:
    """Whether this message continues the previous subject rather than replacing it."""
    return bool(_ADDITIVE_RE.search((message or "").strip().lower()))


def is_market_wide(message: str) -> bool:
    """Whether this message is about the market rather than about one asset."""
    return _has((message or "").lower(), MARKET_WIDE_MARKERS)


def timeframe_in(message: str) -> Optional[str]:
    """
    The candle interval this message asks for, if it names one.

    Longest phrase first, so "4 saatlik" is not read as "saatlik".
    """
    lowered = (message or "").lower()
    matches = [
        (len(word), interval)
        for interval, words in TIMEFRAME_WORDS.items()
        for word in words
        if word in lowered
    ]
    if not matches:
        return None
    return max(matches)[1]
