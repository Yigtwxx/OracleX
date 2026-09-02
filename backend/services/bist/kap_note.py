"""
A grounded read of one KAP filing, written on demand.

Every other note on this realm narrates a board the reader is already looking
at. This one narrates a *primary source*: a company's own disclosure, in its own
words, which the tape prints as a title and a summary and leaves entirely
unexplained. The gap it closes is not "what do these figures mean together" but
"what does a `pay geri alım` resolution actually do to the share count" — the
mechanism a reader who is not a Turkish equity analyst does not carry.

Three properties follow from that and shape the whole module:

* **The filing is immutable, so the note is effectively permanent.** A
  disclosure never changes once filed, which makes it the ideal fingerprint. The
  first reader to open a filing pays for the note; everyone after is served from
  the store, for as long as the entry survives the per-kind prune.
* **The session is bucketed hard, and that is not tidiness.** The equity board
  refreshes every two minutes. Fingerprinting a live `change_pct` beside an
  immutable filing would retire the note on every tick and turn a permanent
  cache entry into a note rewritten all afternoon — the exact failure
  `market_note` documents. The session is therefore snapped to a whole
  percentage point and half a turn of relative volume, and the prompt is
  rendered from those same snapped values, so a cached note can never quote a
  reading that has since moved.
* **The session is optional and its absence is stated.** Around a fifth of the
  tape is filed by Borsa İstanbul itself or by a company whose code the scanner
  does not carry, and the board is a separate upstream that can be down. A
  filing with no share behind it is ordinary, not an error, so the block says so
  and the prompt is told not to characterise a share it was not given.

Nothing here raises. The tape row is complete without the note, so every failure
— AI off, the provider chain down, the equity board unavailable — comes back as
`unavailable` and the row renders exactly as it did before the button existed.
"""

from typing import Any

from services.ai_notes import NoteSpec, get_note
from services.bist.kap_materiality import BAND_UNCLASSIFIED, classify
from services.bist.kap_service import Disclosure

NOTE_SPEC = NoteSpec(
    kind="kap_disclosure",
    prompt="notes/kap_disclosure",
    # Four sentences rather than the usual two or three. A filing needs its
    # class named, its mechanism explained and its size stated or declared
    # absent, and at 200 tokens the mechanism was the clause being dropped.
    max_tokens=280,
    temperature=0.2,
    # A filing does not change, so the fingerprint alone would hold a note
    # forever. A week is the ceiling on how stale the session clause beside it
    # may sound — past that the reading is about a day nobody is looking at.
    max_age_seconds=7 * 24 * 3600,
)

UNKNOWN = "not available"

# KAP summaries run from one line to several paragraphs of boilerplate, and the
# long ones are mostly the standard legal footer. Cut well short of the context
# window: the mechanism is always in the opening, and a filing whose meaning is
# buried 1200 characters in is one the note should be declining to size anyway.
MAX_SUMMARY_CHARS = 1200


def _text(value: Any, limit: int) -> str:
    """A field as trimmed, length-bounded text. Part of the fingerprint."""
    text = " ".join(str(value or "").split())
    return text[:limit].strip()


def _zeroed(value: float) -> float:
    """`-0.0` renders as "-0.0%" and the model quotes it verbatim."""
    return 0.0 if value == 0 else value


def _bucket(value: float | None, step: float) -> float | None:
    if value is None:
        return None
    try:
        return _zeroed(round(round(float(value) / step) * step, 4))
    except (TypeError, ValueError):
        return None


def _pct_bucket(value: float | None, step: float) -> float | None:
    """A fraction as percentage points, snapped to `step`."""
    if value is None:
        return None
    try:
        return _bucket(round(float(value) * 100, 4), step)
    except (TypeError, ValueError):
        return None


# Where the bands sit. Borsa Istanbul's largest companies are a few trillion
# lira and its smallest a few hundred million, so the split is by order of
# magnitude rather than by an even cut of the listing.
SIZE_LABELS = {
    "large": "one of the larger companies on the exchange, above 50 billion lira",
    "mid": "a mid-sized company, between 10 and 50 billion lira",
    "small": "a smaller company, under 10 billion lira",
}


def _size_band(market_cap: float | None) -> str | None:
    if not market_cap:
        return None
    try:
        value = float(market_cap)
    except (TypeError, ValueError):
        return None
    if value >= 50_000_000_000:
        return "large"
    return "mid" if value >= 10_000_000_000 else "small"


def _index_member(indices: Any) -> str | None:
    """The narrowest headline index this share sits in, or None."""
    codes = set(indices or ())
    for code in ("XU030", "XU100"):
        if code in codes:
            return code
    return None


def _minute(stamp: str | None) -> str | None:
    """
    An ISO stamp to the minute.

    The filing's own timestamp, unlike everything else here, is safe to keep at
    this resolution: it is a property of the disclosure and never moves.
    """
    return (stamp or "")[:16] or None


# ── Facts ────────────────────────────────────────────────────────────────────


def disclosure_facts(
    disclosure: Disclosure,
    equity: Any | None = None,
) -> dict[str, Any]:
    """
    Everything the note may speak about, quantized.

    `equity` is an `EquityRow` or None. It is typed loosely on purpose: this
    module has no use for the row beyond five readings, and importing the
    scanner's dataclass here would tie a note to the shape of an upstream client.
    """
    materiality = classify(disclosure.title, disclosure.summary, disclosure.category)
    facts: dict[str, Any] = {
        "index": disclosure.index,
        "event": materiality.event,
        "event_label": materiality.label,
        "score": materiality.score,
        "band": materiality.band,
        "title": _text(disclosure.title, 300),
        "company": _text(disclosure.company, 200),
        "ticker": _text(disclosure.ticker, 20),
        "category": disclosure.category,
        "category_label": _text(disclosure.category_label, 80),
        "published_at": _minute(disclosure.published_at),
        "summary": _text(disclosure.summary, MAX_SUMMARY_CHARS),
        "is_late": bool(disclosure.is_late),
        "session": None,
    }

    if equity is not None:
        facts["session"] = {
            # A whole point, not a tenth. A share that moved from 3.2% to 3.4%
            # between two polls is the same share to a reader and must be the
            # same fingerprint to the store.
            "change_pct": _pct_bucket(getattr(equity, "change_pct", None), 1.0),
            "relative_volume": _bucket(getattr(equity, "relative_volume", None), 0.5),
            "year_pct": _pct_bucket(getattr(equity, "perf_1y", None), 5.0),
            "sector": _text(getattr(equity, "sector", ""), 80) or None,
            # A band rather than a figure. The reading is only ever used to say
            # whether a contract worth two billion lira is large for this
            # company, and a bucketed capitalisation would still move a filing's
            # fingerprint on a day the share ran.
            "size": _size_band(getattr(equity, "market_cap", None)),
            "index_member": _index_member(getattr(equity, "indices", ()) or ()),
        }

    return facts


# ── Rendering ────────────────────────────────────────────────────────────────


# What the tape already tells the reader about this filing's class. The model
# explains it and is forbidden from revising it — `prompts/notes/rules.md` rule
# 4 — because the badge beside the note was drawn from the same reading, and a
# paragraph arguing with the chip above it is the one outcome that reads as a
# broken page rather than as a disagreement.
_BAND_SENTENCES = {
    "high": (
        "The board classified this as a filing that changes the company's "
        "capital, ownership or earnings, and drew it as such on the row"
    ),
    "medium": (
        "The board classified this as a filing a holder acts on without the "
        "capital changing, and drew it as such on the row"
    ),
    "routine": (
        "The board classified this as a mechanical filing — real, and not "
        "company news — and drew it as such on the row"
    ),
}


def _classification_line(facts: dict[str, Any]) -> str:
    if facts["band"] == BAND_UNCLASSIFIED:
        return (
            "- Classification: none. This is one of KAP's free-text forms, whose "
            "title is a form name and says nothing about the contents, so the "
            "board put no band on the row and the summary below is the only "
            "account of what this filing is. Say what class of event it turns "
            "out to be."
        )
    sentence = _BAND_SENTENCES.get(facts["band"], "")
    return (
        f"- Classification, computed before you saw it: {facts['event_label']}, "
        f"scored {facts['score']} out of 10. {sentence}. The score orders filings "
        f"against each other and measures nothing — do not read a precision into "
        f"it, and do not overturn the class."
    )


def _show_pct(value: float | None) -> str:
    return UNKNOWN if value is None else f"{value:+.0f}%"


def disclosure_values(facts: dict[str, Any]) -> dict[str, str]:
    """The prompt's blocks, rendered from `facts` and from nothing else."""
    filing = [
        f"- Title, as filed: {facts['title'] or UNKNOWN}",
        f"- Filing type: {facts['category_label']} ({facts['category'] or 'n/a'})",
        f"- Published: {facts['published_at'] or UNKNOWN}",
        _classification_line(facts),
    ]
    if facts["is_late"]:
        filing.append(
            "- KAP marks this filing as late: the company disclosed it after the "
            "deadline the rules set for it"
        )
    if facts["summary"]:
        filing.append(f"- Summary, as filed:\n{facts['summary']}")
    else:
        filing.append(
            "- Summary, as filed: none. KAP carries no body text for this "
            "disclosure — the substance is in an attachment this board cannot "
            "read, so the filing can be classified but not sized"
        )

    session = facts["session"]
    company = [
        f"- Company: {facts['company'] or UNKNOWN}",
        f"- Ticker: {facts['ticker'] or 'none — this filing is not attributed to a listed share'}",
    ]
    if session:
        if session["sector"]:
            company.append(f"- Sector: {session['sector']}")
        if session["size"]:
            company.append(f"- Size: {SIZE_LABELS[session['size']]}")
        if session["index_member"]:
            company.append(f"- Index membership: {session['index_member']}")

    if not session:
        market = (
            "No session reading was available for this filing. Either it carries "
            "no ticker — Borsa İstanbul and the exchange's own notices are filed "
            "this way — or the equity board could not be reached. Do not "
            "characterise the share, do not say whether it rose or fell, and do "
            "not infer a reaction to this filing."
        )
    else:
        lines = [
            "Readings are rounded — a whole percentage point, half a turn of "
            "volume — and are the state of the tape around this filing, not a "
            "measurement of its effect.",
            f"- Session change: {_show_pct(session['change_pct'])}",
        ]
        if session["relative_volume"] is not None:
            lines.append(
                f"- Volume against this share's own average: {session['relative_volume']:.1f}x"
            )
        if session["year_pct"] is not None:
            lines.append(
                f"- Trailing year, nominal and before inflation: {_show_pct(session['year_pct'])}"
            )
        market = "\n".join(lines)

    return {
        "filing": "\n".join(filing),
        "company": "\n".join(company),
        "market": market,
    }


# ── Entry point ──────────────────────────────────────────────────────────────


async def note_for_disclosure(
    disclosure: Disclosure,
    equity: Any | None = None,
) -> dict[str, Any]:
    facts = disclosure_facts(disclosure, equity)
    return await get_note(NOTE_SPEC, facts, disclosure_values(facts))
