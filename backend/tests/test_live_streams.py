"""
Characterization tests for the broadcast probe and the headline tape.

The probe reads YouTube's HTML, so its failure mode is the quiet one: a markup
change, or a body truncated before the markers, makes every channel report as
offline rather than raising. These pin the two signals it depends on and the
distinction between "off air" and "could not tell".
"""

from datetime import UTC, datetime

import pytest

from services import live_stream_service as lss
from services import live_tape_service as lts

CANONICAL_LIVE = '<link rel="canonical" href="https://www.youtube.com/watch?v=9NyxcX3rhQs">'
CANONICAL_OFFLINE = (
    '<link rel="canonical" href="https://www.youtube.com/channel/UCvJJ_dzjViJCoLf5uKUTwoA">'
)
META_TITLE = '<meta name="title" content="LIVE: CNBC Marathon &amp; deep dives">'


def _page(*parts: str) -> str:
    return f"<html><head>{''.join(parts)}</head><body></body></html>"


@pytest.fixture
def fake_fetch(monkeypatch):
    """Replaces both fetch paths so no test here touches the network."""

    def _install(body: str | None, *, impersonated: str | None = None):
        async def _get_text(url, **kwargs):
            if body is None:
                raise RuntimeError("blocked")
            return body

        async def _get_text_impersonated(url, **kwargs):
            if impersonated is None:
                raise RuntimeError("blocked")
            return impersonated

        monkeypatch.setattr(lss.http_client, "get_text", _get_text)
        monkeypatch.setattr(lss.http_client, "get_text_impersonated", _get_text_impersonated)

    return _install


async def test_probe_reads_the_video_id_and_title_when_live(fake_fetch):
    fake_fetch(_page(CANONICAL_LIVE, META_TITLE, '"isLive":true'))

    state = await lss.probe_youtube_live("UCvJJ_dzjViJCoLf5uKUTwoA")

    assert state.is_live is True
    assert state.video_id == "9NyxcX3rhQs"
    # The meta tag is escaped; a literal "&amp;" in the UI would be the tell.
    assert state.title == "LIVE: CNBC Marathon & deep dives"
    assert state.reachable is True


async def test_probe_reads_offline_when_the_canonical_stays_on_the_channel(fake_fetch):
    fake_fetch(_page(CANONICAL_OFFLINE))

    state = await lss.probe_youtube_live("UCvJJ_dzjViJCoLf5uKUTwoA")

    assert state.is_live is False
    assert state.video_id is None
    assert state.reachable is True, "A page that answered is not a failed probe"


async def test_probe_requires_the_live_marker_as_well_as_the_redirect(fake_fetch):
    """
    The canonical redirect alone also fires for a stream that has just ended.
    Without the second signal a channel would read as live for hours after.
    """
    fake_fetch(_page(CANONICAL_LIVE, META_TITLE))

    state = await lss.probe_youtube_live("UCvJJ_dzjViJCoLf5uKUTwoA")

    assert state.is_live is False
    assert state.reachable is True


async def test_probe_reports_unreachable_rather_than_offline_when_walled(fake_fetch):
    """
    A consent wall or bot-block must not be rendered as "nobody is live" — that
    is a claim about the world, and the UI shows it as one.
    """
    fake_fetch(None, impersonated=None)

    state = await lss.probe_youtube_live("UCvJJ_dzjViJCoLf5uKUTwoA")

    assert state.is_live is False
    assert state.reachable is False


async def test_probe_retries_through_the_browser_fingerprint(fake_fetch):
    """The plain client is tried first; a stub answer falls through to curl_cffi."""
    fake_fetch(
        _page("<title>consent</title>"),
        impersonated=_page(CANONICAL_LIVE, META_TITLE, '"isLive":true'),
    )

    state = await lss.probe_youtube_live("UCvJJ_dzjViJCoLf5uKUTwoA")

    assert state.is_live is True
    assert state.video_id == "9NyxcX3rhQs"


def test_every_curated_channel_id_looks_like_a_youtube_id():
    """A malformed id fails silently — the channel simply never reports live."""
    for channel in lss.CHANNELS:
        assert channel.channel_id.startswith("UC"), f"{channel.key}: {channel.channel_id}"
        assert len(channel.channel_id) == 24, f"{channel.key}: {channel.channel_id}"


def test_the_channel_split_covers_every_channel_exactly_once():
    assert set(lss.EVENT_CHANNELS) | set(lss.MARKET_CHANNELS) == set(lss.CHANNELS)
    assert not set(lss.EVENT_CHANNELS) & set(lss.MARKET_CHANNELS)


def test_channel_embed_url_needs_no_video_id():
    """This is the fallback that keeps the player usable when a probe fails."""
    url = lss.channel_embed_url("UCIALMKvObZNtJ6AmdCLP7Lg")

    assert url == (
        "https://www.youtube-nocookie.com/embed/live_stream?channel=UCIALMKvObZNtJ6AmdCLP7Lg"
    )


# ==========================================
# HEADLINE TAPE
# ==========================================


class _FakeNews:
    def __init__(self, news_id, title, summary="", source="Test", published_at=None):
        self.id = news_id
        self.title = title
        self.summary = summary
        self.source = source
        self.published_at = published_at or datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
        self.symbol = None
        self.url = "https://example.invalid"


@pytest.fixture
def fake_news_cache(monkeypatch):
    def _install(items):
        monkeypatch.setattr(lts, "get_news_cache", lambda: {item.id: item for item in items})

    return _install


def test_tape_keeps_only_headlines_it_can_tag(fake_news_cache):
    fake_news_cache(
        [
            _FakeNews("1", "Powell says the committee is not on a preset course"),
            _FakeNews("2", "Solana validator client ships a patch"),
        ]
    )

    result = lts.fetch_tape()

    assert [item["id"] for item in result["items"]] == ["1"]
    assert result["items"][0]["tags"] == ["fed"]


def test_tape_can_carry_several_tags(fake_news_cache):
    fake_news_cache([_FakeNews("1", "Trump tariff plan lands before the CPI print")])

    tags = lts.fetch_tape()["items"][0]["tags"]

    assert set(tags) == {"politics", "trade", "inflation"}


def test_tape_sorts_newest_first(fake_news_cache):
    fake_news_cache(
        [
            _FakeNews("old", "CPI beats", published_at=datetime(2026, 8, 11, 9, 0, tzinfo=UTC)),
            _FakeNews("new", "CPI revised", published_at=datetime(2026, 8, 11, 14, 0, tzinfo=UTC)),
        ]
    )

    assert [item["id"] for item in lts.fetch_tape()["items"]] == ["new", "old"]


def test_tape_survives_a_naive_timestamp(fake_news_cache):
    """Feed dates arrive naive often enough that sorting them would otherwise raise."""
    fake_news_cache(
        [
            _FakeNews("naive", "CPI beats", published_at=datetime(2026, 8, 11, 9, 0)),
            _FakeNews(
                "aware", "FOMC minutes", published_at=datetime(2026, 8, 11, 14, 0, tzinfo=UTC)
            ),
        ]
    )

    assert len(lts.fetch_tape()["items"]) == 2


def test_tape_flags_an_unfilled_cache_rather_than_calling_it_quiet(fake_news_cache):
    fake_news_cache([])

    result = lts.fetch_tape()

    assert result["items"] == []
    assert result["warming"] is True, "An empty cache is not the same as a quiet wire"


def test_tape_respects_the_limit(fake_news_cache):
    fake_news_cache([_FakeNews(str(i), f"Fed speaker {i} on rates") for i in range(10)])

    assert len(lts.fetch_tape(limit=3)["items"]) == 3
