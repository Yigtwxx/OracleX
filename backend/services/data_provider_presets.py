"""
Optional market-data upstreams a reader can supply a key for.

These are not the LLM providers. Each one here is an upstream the terminal works
*without* — the page still renders, it just carries less: no inflation series,
thirty days of open interest instead of years. That is why the panel these feed
sells the upgrade rather than blocking the page.

`scope` is the whole reason this registry exists rather than a list of strings:

  "user"   — resolved per request from the caller's stored key, falling back to
             the server's .env value. Safe because the fetch is request-scoped
             and the answer is public data that every reader may share.
  "server" — .env only. The upstream feeds a shared artefact rebuilt by a
             scheduler that carries no user_id, so a per-reader key could not be
             applied to it even if one were stored.

`signup_url` is shown to the reader as the place to get a key, so it must point
at the page that actually issues one, not the provider's home page.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DataProviderPreset:
    """Everything the settings panel and the resolver need for one upstream."""

    label: str
    env_var: str
    scope: Literal["user", "server"]
    # What the reader gains by supplying a key. Rendered verbatim in the UI, so
    # it names the surface rather than the internal service.
    benefit: str
    signup_url: str
    # Shown as the input's placeholder; also tells the reader what shape the
    # value has, which for SEC is an email address rather than a key.
    placeholder: str


DATA_PROVIDERS: dict[str, DataProviderPreset] = {
    "evds": DataProviderPreset(
        label="TCMB EVDS",
        env_var="TCMB_EVDS_API_KEY",
        scope="user",
        benefit=(
            "Turkish CPI, which is what turns every BIST return real instead of "
            "nominal — the Bilanço real/nominal toggle, the Halka Arz frame and the "
            "real-return columns on Fonlar and Hisseler."
        ),
        signup_url="https://evds2.tcmb.gov.tr/index.php?/evds/userGuideRest",
        placeholder="Paste your EVDS API key",
    ),
    "coinalyze": DataProviderPreset(
        label="Coinalyze",
        env_var="COINALYZE_API_KEY",
        scope="user",
        benefit=(
            "Full daily open-interest history on the Derivatives board. Without a "
            "key it is served from the exchanges' own statistics endpoints, which "
            "keep about thirty days."
        ),
        signup_url="https://coinalyze.net/futures-data/api/",
        placeholder="Paste your Coinalyze API key",
    ),
    # Read-only in the panel. EDGAR's fair-access policy wants a contact address
    # on every request, and the ownership board it feeds is one shared artefact
    # rebuilt daily by a scheduler with no caller attached — so a per-reader
    # value has nothing to apply itself to. It is listed anyway because a reader
    # looking at a stale Ownership board deserves to know why.
    "sec": DataProviderPreset(
        label="SEC EDGAR contact address",
        env_var="SEC_USER_AGENT",
        scope="server",
        benefit=(
            "Refreshes the Ownership board from 13F-HR and Form 4 filings. Without "
            "it the board still renders, from the last reading that was stored."
        ),
        signup_url="https://www.sec.gov/os/webmaster-faq#developers",
        placeholder="Oracle-X you@example.com",
    ),
}

# The ones a reader can actually store a key for.
USER_PROVIDERS: tuple[str, ...] = tuple(
    name for name, preset in DATA_PROVIDERS.items() if preset.scope == "user"
)


def is_user_provider(name: str) -> bool:
    """Whether `name` accepts a per-reader key."""
    return name in USER_PROVIDERS
