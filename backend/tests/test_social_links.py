"""
Tests for the social-link platform registry.

These handles are self-declared: nothing here proves an account belongs to the
person who typed it. What the registry *is* responsible for is that a stored
link points where its platform says it should — the URL is built from a
template server-side, so a caller cannot smuggle an arbitrary destination in
under a trusted-looking platform name.
"""

import asyncio
from types import SimpleNamespace

import pytest

from services import social_links_service
from services.social_links_service import (
    MAX_CUSTOM,
    MAX_LINKS,
    InvalidLink,
    build_url,
    normalise_handle,
    validate_custom,
    validate_links,
)


@pytest.mark.parametrize(
    "platform,raw,expected",
    [
        ("x", "@yigtwx", "yigtwx"),
        ("x", "  yigtwx  ", "yigtwx"),
        ("github", "Yigtwxx", "Yigtwxx"),
        ("substack", "My-Letter", "my-letter"),
        ("discord", "Yigtwx", "yigtwx"),
    ],
)
def test_handles_are_trimmed_stripped_of_at_and_cased_per_platform(platform, raw, expected):
    assert normalise_handle(platform, raw) == expected


@pytest.mark.parametrize(
    "platform,handle,expected",
    [
        ("x", "yigtwx", "https://x.com/yigtwx"),
        ("telegram", "yigtwx", "https://t.me/yigtwx"),
        ("github", "Yigtwxx", "https://github.com/Yigtwxx"),
        ("youtube", "Yigtwx", "https://www.youtube.com/@Yigtwx"),
        ("substack", "my-letter", "https://my-letter.substack.com"),
        ("tradingview", "yigtwx", "https://www.tradingview.com/u/yigtwx/"),
    ],
)
def test_urls_are_derived_from_the_platform_template(platform, handle, expected):
    assert build_url(platform, handle) == expected


def test_discord_has_no_url_because_usernames_are_not_addressable():
    assert build_url("discord", "yigtwx") is None


@pytest.mark.parametrize(
    "platform,handle",
    [
        ("x", "a" * 16),  # over 15 characters
        ("x", "has spaces"),
        ("x", "semi;colon"),
        ("github", "-leading-hyphen"),
        ("telegram", "abc"),  # under 5 characters
        ("reddit", "no"),  # under 3 characters
        ("substack", "Not_Lowercase_Slug"),
    ],
)
def test_handles_that_do_not_match_their_platform_are_refused(platform, handle):
    with pytest.raises(InvalidLink):
        validate_links([{"platform": platform, "handle": handle}])


def test_an_unknown_platform_is_refused():
    with pytest.raises(InvalidLink, match="support"):
        validate_links([{"platform": "myspace", "handle": "someone"}])


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD4=",
        "file:///etc/passwd",
        "ftp://example.com",
        "example.com",  # no scheme at all
    ],
)
def test_custom_links_accept_only_http_and_https(url):
    with pytest.raises(InvalidLink):
        validate_custom("My site", url)


def test_a_custom_link_keeps_its_label_and_url():
    assert validate_custom("  My Blog  ", "https://example.com/x") == (
        "My Blog",
        "https://example.com/x",
    )


def test_a_custom_link_needs_a_label():
    with pytest.raises(InvalidLink, match="label"):
        validate_custom("   ", "https://example.com")


def test_the_same_known_platform_cannot_appear_twice():
    with pytest.raises(InvalidLink, match="once"):
        validate_links(
            [
                {"platform": "x", "handle": "one"},
                {"platform": "x", "handle": "two"},
            ]
        )


def test_custom_links_are_capped():
    items = [
        {"platform": "custom", "label": f"Site {i}", "url": f"https://example.com/{i}"}
        for i in range(MAX_CUSTOM + 1)
    ]
    with pytest.raises(InvalidLink, match="custom"):
        validate_links(items)


def test_the_total_number_of_links_is_capped():
    items = [
        {"platform": "custom", "label": f"Site {i}", "url": f"https://example.com/{i}"}
        for i in range(MAX_LINKS + 1)
    ]
    with pytest.raises(InvalidLink):
        validate_links(items)


def test_validate_links_assigns_position_from_array_order():
    rows = validate_links(
        [
            {"platform": "github", "handle": "Yigtwxx"},
            {"platform": "x", "handle": "yigtwx"},
        ]
    )
    assert [r["position"] for r in rows] == [0, 1]
    assert [r["platform"] for r in rows] == ["github", "x"]


def test_position_supplied_by_the_caller_is_ignored():
    rows = validate_links([{"platform": "x", "handle": "yigtwx", "position": 99}])
    assert rows[0]["position"] == 0


def test_a_url_supplied_for_a_known_platform_is_ignored():
    rows = validate_links(
        [{"platform": "x", "handle": "yigtwx", "url": "https://evil.example/phish"}]
    )
    assert rows[0]["url"] == "https://x.com/yigtwx"


# ═══════════════════════════════════════════════════════════════════════════════
# PERSISTENCE AND THE PUBLIC PAYLOAD
# ═══════════════════════════════════════════════════════════════════════════════
#
# A fake Supabase client rather than the real project: the behaviour worth
# pinning is *which columns leave the building*, and that is decided here, not
# in Postgres.


class FakeQuery:
    """Records the calls made against one table and replays a fixed result."""

    def __init__(self, table: "FakeTable"):
        self.table = table

    def select(self, columns):
        self.table.selected = columns
        return self

    def insert(self, rows):
        self.table.inserted = rows
        return self

    def delete(self):
        self.table.deleted = True
        return self

    def eq(self, column, value):
        self.table.filters.append((column, value))
        return self

    def order(self, column):
        return self

    def limit(self, n):
        return self

    def execute(self):
        return SimpleNamespace(data=self.table.rows)


class FakeTable:
    def __init__(self, rows):
        self.rows = rows
        self.selected = None
        self.inserted = None
        self.deleted = False
        self.filters: list = []


class FakeClient:
    def __init__(self, tables, rpc_result=None):
        self.tables = tables
        self.rpc_result = (
            rpc_result
            if rpc_result is not None
            else [{"post_karma": 0, "comment_karma": 0, "total_karma": 0}]
        )
        self.rpc_calls: list = []

    def table(self, name):
        return FakeQuery(self.tables[name])

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=self.rpc_result))


def _install(monkeypatch, client):
    monkeypatch.setattr(social_links_service, "_client", lambda: client)


def test_the_public_payload_never_includes_the_email(monkeypatch):
    client = FakeClient(
        {
            "profiles": FakeTable(
                [
                    {
                        "id": "user-abc",
                        "full_name": "Yigit",
                        "avatar_url": None,
                        "bio": "Hello",
                        "subscription_plan": "free",
                        "created_at": "2026-01-01T00:00:00+00:00",
                    }
                ]
            ),
            "profile_social_links": FakeTable([]),
        }
    )
    _install(monkeypatch, client)

    result = asyncio.run(social_links_service.get_public_profile("user-abc"))

    assert result is not None
    assert "email" not in result
    # The column list is explicit, not a wildcard: the backend holds the
    # service-role key, so RLS would not catch a `select("*")` here.
    assert "*" not in client.tables["profiles"].selected
    assert "email" not in client.tables["profiles"].selected


def test_the_public_payload_carries_links_and_karma(monkeypatch):
    client = FakeClient(
        {
            "profiles": FakeTable([{"id": "user-abc", "full_name": "Yigit"}]),
            "profile_social_links": FakeTable(
                [
                    {
                        "platform": "x",
                        "handle": "yigtwx",
                        "label": None,
                        "url": "https://x.com/yigtwx",
                        "position": 0,
                    }
                ]
            ),
        },
        rpc_result=[{"post_karma": 4, "comment_karma": 1, "total_karma": 5}],
    )
    _install(monkeypatch, client)

    result = asyncio.run(social_links_service.get_public_profile("user-abc"))

    assert result is not None
    assert result["social_links"][0]["handle"] == "yigtwx"
    assert result["karma"]["total_karma"] == 5


def test_a_missing_profile_is_none_not_an_empty_shell(monkeypatch):
    client = FakeClient({"profiles": FakeTable([]), "profile_social_links": FakeTable([])})
    _install(monkeypatch, client)

    assert asyncio.run(social_links_service.get_public_profile("nobody")) is None


def test_karma_comes_from_the_rpc(monkeypatch):
    client = FakeClient(
        {"profiles": FakeTable([]), "profile_social_links": FakeTable([])},
        rpc_result=[{"post_karma": 7, "comment_karma": 3, "total_karma": 10}],
    )
    _install(monkeypatch, client)

    assert asyncio.run(social_links_service.get_karma("user-abc")) == {
        "post_karma": 7,
        "comment_karma": 3,
        "total_karma": 10,
    }
    assert client.rpc_calls == [("community_user_karma", {"uid": "user-abc"})]


def test_karma_for_a_user_with_no_activity_is_zero(monkeypatch):
    client = FakeClient(
        {"profiles": FakeTable([]), "profile_social_links": FakeTable([])},
        rpc_result=[],
    )
    _install(monkeypatch, client)

    assert asyncio.run(social_links_service.get_karma("user-abc")) == {
        "post_karma": 0,
        "comment_karma": 0,
        "total_karma": 0,
    }


def test_replace_links_clears_the_old_set_before_inserting(monkeypatch):
    table = FakeTable([])
    client = FakeClient({"profile_social_links": table})
    _install(monkeypatch, client)

    asyncio.run(
        social_links_service.replace_links("user-abc", [{"platform": "x", "handle": "yigtwx"}])
    )

    assert table.deleted is True
    assert table.inserted == [
        {
            "user_id": "user-abc",
            "platform": "x",
            "handle": "yigtwx",
            "label": None,
            "url": "https://x.com/yigtwx",
            "position": 0,
        }
    ]


def test_replace_links_with_an_empty_list_only_deletes(monkeypatch):
    table = FakeTable([])
    client = FakeClient({"profile_social_links": table})
    _install(monkeypatch, client)

    assert asyncio.run(social_links_service.replace_links("user-abc", [])) == []
    assert table.deleted is True
    assert table.inserted is None


def test_an_invalid_link_is_rejected_before_anything_is_deleted(monkeypatch):
    table = FakeTable([])
    client = FakeClient({"profile_social_links": table})
    _install(monkeypatch, client)

    with pytest.raises(social_links_service.InvalidLink):
        asyncio.run(
            social_links_service.replace_links("user-abc", [{"platform": "x", "handle": "!!"}])
        )

    # The whole point of validating first: a bad row must not cost the user the
    # links they already had.
    assert table.deleted is False


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTER WIRING
# ═══════════════════════════════════════════════════════════════════════════════


def test_the_router_exposes_the_two_new_paths():
    from routers import profile as profile_router

    paths = {
        (route.path, method)
        for route in profile_router.router.routes
        for method in getattr(route, "methods", set())
    }
    assert ("/api/profile/social-links", "PUT") in paths
    assert ("/api/profile/public/{user_id}", "GET") in paths


def test_the_dead_oauth_endpoints_are_gone():
    from routers import profile as profile_router

    paths = {route.path for route in profile_router.router.routes}
    # POST /api/profile/accounts/{provider} accepted an access_token straight
    # from the request body and stored it. No OAuth application exists for any
    # provider, so nothing ever called it with a real one.
    assert "/api/profile/accounts" not in paths
    assert "/api/profile/accounts/{provider}" not in paths


def test_profile_service_no_longer_carries_the_connected_account_helpers():
    from services import profile_service

    for gone in ("connect_account", "disconnect_account", "get_connected_accounts"):
        assert not hasattr(profile_service, gone)


def test_the_bio_field_is_accepted_on_profile_update():
    from routers.profile import ProfileUpdate

    assert "bio" in ProfileUpdate.model_fields


def test_bio_survives_the_profile_service_allowlist(monkeypatch):
    """
    `update_user_profile` filters its input against an allowlist, so accepting
    `bio` at the router is not enough — a column missing from that list is
    dropped silently, and the save would report success having written nothing.
    """
    import asyncio as _asyncio

    from services import profile_service

    written: dict = {}

    class Recorder:
        def table(self, name):
            return self

        def update(self, data):
            written.update(data)
            return self

        def eq(self, column, value):
            return self

        def execute(self):
            return SimpleNamespace(data=[{"id": "user-abc"}])

    monkeypatch.setattr(profile_service, "get_supabase", lambda: Recorder())

    assert _asyncio.run(profile_service.update_user_profile("user-abc", {"bio": "Hello"})) is True
    assert written.get("bio") == "Hello"
