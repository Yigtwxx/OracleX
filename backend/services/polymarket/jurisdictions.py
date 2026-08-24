"""
Where Polymarket may be traded from.

This is the one genuinely geographic fact about Polymarket that is published, and
it is worth being precise about what it is *not*. It is not a map of where the
money comes from. Polymarket runs non-custodially on Polygon; `/trades` and
`/holders` identify a counterparty as a `proxyWallet` and nothing else, and no
public endpoint anywhere exposes a trader's location. A "bets by country"
choropleth cannot be built from real data, and the honest substitute is a map of
where betting is *permitted*.

The lists below are transcribed from Polymarket's own geoblock documentation on
2026-08-21 (https://docs.polymarket.com/api-reference/geoblock), which publishes
them as ISO 3166-1 alpha-2 country codes and ISO 3166-2 sub-national codes.
Because they are transcribed rather than fetched, they will drift: the single
live endpoint Polymarket offers, `GET https://polymarket.com/api/geoblock`,
geolocates the *caller's own IP* and returns one row, so there is nothing to
poll. `SOURCE_RETRIEVED` rides on the payload so the UI can say how old this is
rather than implying it is live.

Two honesty constraints are built into the shape:

**Sub-national restrictions are not country-wide.** Four Canadian provinces are
close-only and the rest of Canada is not; three occupied Ukrainian regions are
blocked and the rest of Ukraine is not. Painting either country solid would
state something false, so those carry `partial=True` and the regions that
actually apply.

**"Close-only" is not "blocked".** A close-only jurisdiction can still settle
existing positions. Collapsing the three tiers into a binary would turn a
regulatory nuance into a prohibition.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: When the lists below were read off the documentation. Shown to the reader.
SOURCE_RETRIEVED = "2026-08-21"
SOURCE_URL = "https://docs.polymarket.com/api-reference/geoblock"

TIER_BLOCKED = "blocked"
TIER_CLOSE_ONLY = "close_only"
TIER_FRONTEND_ONLY = "frontend_only"

TIER_LABEL = {
    TIER_BLOCKED: "Blocked entirely",
    TIER_CLOSE_ONLY: "Close-only (site and API)",
    TIER_FRONTEND_ONLY: "Close-only (site only)",
}

TIER_DETAIL = {
    TIER_BLOCKED: "No new orders, and existing positions cannot be closed.",
    TIER_CLOSE_ONLY: "Existing positions can be closed; no new ones may be opened.",
    TIER_FRONTEND_ONLY: "Close-only on the Polymarket site; the API itself is unrestricted.",
}


@dataclass(frozen=True)
class Jurisdiction:
    code: str
    name: str
    tier: str
    #: True when only named sub-national regions are affected. A partial
    #: restriction painted as a whole country is a false statement about the
    #: rest of it.
    partial: bool = False
    regions: tuple[str, ...] = field(default_factory=tuple)
    note: str = ""


JURISDICTIONS: tuple[Jurisdiction, ...] = (
    # OFAC-sanctioned — blocked on both the frontend and the API.
    Jurisdiction("IR", "Iran", TIER_BLOCKED),
    Jurisdiction("SY", "Syria", TIER_BLOCKED),
    Jurisdiction("CU", "Cuba", TIER_BLOCKED),
    Jurisdiction("KP", "North Korea", TIER_BLOCKED),
    Jurisdiction(
        "UA",
        "Ukraine",
        TIER_BLOCKED,
        partial=True,
        regions=("UA-43 Crimea", "UA-14 Donetsk", "UA-09 Luhansk"),
        note="Only the occupied regions are blocked; the rest of Ukraine is not restricted.",
    ),
    # Regulatory — close-only on both the frontend and the API.
    Jurisdiction("AU", "Australia", TIER_CLOSE_ONLY),
    Jurisdiction("BY", "Belarus", TIER_CLOSE_ONLY),
    Jurisdiction("BE", "Belgium", TIER_CLOSE_ONLY),
    Jurisdiction("BI", "Burundi", TIER_CLOSE_ONLY),
    Jurisdiction("BR", "Brazil", TIER_CLOSE_ONLY),
    Jurisdiction(
        "CA",
        "Canada",
        TIER_CLOSE_ONLY,
        partial=True,
        regions=("British Columbia", "Ontario", "Alberta", "Quebec"),
        note="Four provinces are close-only; the rest of Canada is not restricted.",
    ),
    Jurisdiction("CF", "Central African Republic", TIER_CLOSE_ONLY),
    Jurisdiction("CD", "Congo (Kinshasa)", TIER_CLOSE_ONLY),
    Jurisdiction("ET", "Ethiopia", TIER_CLOSE_ONLY),
    Jurisdiction("FR", "France", TIER_CLOSE_ONLY),
    Jurisdiction("DE", "Germany", TIER_CLOSE_ONLY),
    Jurisdiction("IQ", "Iraq", TIER_CLOSE_ONLY),
    Jurisdiction("IT", "Italy", TIER_CLOSE_ONLY),
    Jurisdiction("LB", "Lebanon", TIER_CLOSE_ONLY),
    Jurisdiction("LY", "Libya", TIER_CLOSE_ONLY),
    Jurisdiction("MM", "Myanmar", TIER_CLOSE_ONLY),
    Jurisdiction("NZ", "New Zealand", TIER_CLOSE_ONLY),
    Jurisdiction("NI", "Nicaragua", TIER_CLOSE_ONLY),
    Jurisdiction("PL", "Poland", TIER_CLOSE_ONLY),
    Jurisdiction("RU", "Russia", TIER_CLOSE_ONLY),
    Jurisdiction("SG", "Singapore", TIER_CLOSE_ONLY),
    Jurisdiction("SO", "Somalia", TIER_CLOSE_ONLY),
    Jurisdiction("SK", "Slovakia", TIER_CLOSE_ONLY),
    Jurisdiction("SS", "South Sudan", TIER_CLOSE_ONLY),
    Jurisdiction("SD", "Sudan", TIER_CLOSE_ONLY),
    Jurisdiction("TW", "Taiwan", TIER_CLOSE_ONLY),
    Jurisdiction("TH", "Thailand", TIER_CLOSE_ONLY),
    Jurisdiction("GB", "United Kingdom", TIER_CLOSE_ONLY),
    Jurisdiction(
        "US",
        "United States",
        TIER_CLOSE_ONLY,
        note=(
            "This is the international exchange. Polymarket US, a separate "
            "CFTC-regulated venue, is open to US residents with full KYC."
        ),
    ),
    Jurisdiction("UM", "United States Minor Outlying Islands", TIER_CLOSE_ONLY),
    Jurisdiction("VE", "Venezuela", TIER_CLOSE_ONLY),
    Jurisdiction("YE", "Yemen", TIER_CLOSE_ONLY),
    Jurisdiction("ZW", "Zimbabwe", TIER_CLOSE_ONLY),
    # Regulatory — close-only on the frontend only.
    Jurisdiction("IE", "Ireland", TIER_FRONTEND_ONLY),
    Jurisdiction("JP", "Japan", TIER_FRONTEND_ONLY),
    Jurisdiction("MT", "Malta", TIER_FRONTEND_ONLY, note="Sports markets only."),
    Jurisdiction("NL", "Netherlands", TIER_FRONTEND_ONLY),
)

BY_CODE = {j.code: j for j in JURISDICTIONS}


def as_layer() -> dict:
    """The jurisdiction layer, with its provenance attached."""
    return {
        "provenance": "measured",
        "source_url": SOURCE_URL,
        "retrieved": SOURCE_RETRIEVED,
        "tier_labels": TIER_LABEL,
        "tier_details": TIER_DETAIL,
        "countries": [
            {
                "code": j.code,
                "name": j.name,
                "tier": j.tier,
                "partial": j.partial,
                "regions": list(j.regions),
                "note": j.note,
            }
            for j in JURISDICTIONS
        ],
    }
