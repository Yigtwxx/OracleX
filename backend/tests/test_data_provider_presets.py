"""
Tests for the data provider registry.

The signup links are pinned rather than merely shape-checked. Every one of the
first three shipped was wrong in a way no type or lint catches — a 404, a page
that answers "Access forbidden" to anyone not signed in, and a host that had
moved on a version — and a reader who clicks "Get a key" and lands on a dead
page has no way to tell whether the feature is broken or the link is. Changing
one of these should mean opening it first, which is what failing this test asks
for.
"""

from services.data_provider_presets import (
    DATA_PROVIDERS,
    USER_PROVIDERS,
    is_user_provider,
)

# Opened in a browser and confirmed to render the page a reader needs.
VERIFIED_SIGNUP_URLS = {
    # evds2's deep link 302s here; this is where "BENİM SAYFAM" issues the key.
    "evds": "https://evds3.tcmb.gov.tr/",
    # The public API doc. The account page that actually mints the key answers
    # "Access forbidden" when signed out, so it is the wrong place to send
    # someone who does not have an account yet.
    "coinalyze": "https://api.coinalyze.net/v1/doc/",
    # /os/webmaster-faq 301s here.
    "sec": "https://www.sec.gov/about/webmaster-frequently-asked-questions#developers",
}


def test_every_provider_has_a_verified_signup_url():
    assert {name: p.signup_url for name, p in DATA_PROVIDERS.items()} == VERIFIED_SIGNUP_URLS


def test_signup_urls_are_https():
    for name, preset in DATA_PROVIDERS.items():
        assert preset.signup_url.startswith("https://"), name


def test_every_preset_is_fully_populated():
    """A blank field renders as an empty row rather than raising."""
    for name, preset in DATA_PROVIDERS.items():
        assert preset.label, name
        assert preset.env_var, name
        assert preset.benefit, name
        assert preset.placeholder, name


def test_user_providers_are_exactly_the_user_scoped_ones():
    assert USER_PROVIDERS == ("evds", "coinalyze")
    assert all(DATA_PROVIDERS[name].scope == "user" for name in USER_PROVIDERS)


def test_sec_is_server_scoped():
    """It feeds a scheduled shared artefact; a per-reader value has no request."""
    assert DATA_PROVIDERS["sec"].scope == "server"
    assert not is_user_provider("sec")


def test_unknown_names_are_not_user_providers():
    assert not is_user_provider("nonesuch")
    assert not is_user_provider("")
