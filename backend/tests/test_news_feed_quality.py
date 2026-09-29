"""
Two feed defects that reached the track record as scored verdicts.

Tree of Alpha republishes the desks' headlines with the desk's name in front —
"DECRYPT: Strategy Sells $105M in Bitcoin" beside Decrypt's own "Strategy Sells
$105M in Bitcoin" — so a de-duplication keyed on the raw title kept both, and
the same story was analysed and scored twice against the same price window.

The same prefix is how "THE BLOCK: Crypto firms urge SEC…" and "THE
INDEPENDENT: Hunter Biden launching crypto meme coin…" were both attributed to
the THE token and scored against a chart that had nothing to do with either.
"""

import asyncio
from datetime import datetime

from models.schemas import NewsItem
from services.news_service import _dedupe, _treeofalpha_symbol
from services.symbol_detection_service import is_uncashtagged_acronym


def _item(news_id: str, title: str, source: str) -> NewsItem:
    return NewsItem(
        id=news_id,
        title=title,
        summary="",
        source=source,
        published_at=datetime(2026, 8, 3, 12, 0),
        asset_type="crypto",
    )


def test_desk_prefixed_republish_is_a_duplicate():
    tree = _item(
        "a",
        "DECRYPT: Strategy Sells $105M in Bitcoin as Dollar Reserve Hits $4B",
        "Tree of Alpha · DECRYPT",
    )
    desk = _item("b", "Strategy Sells $105M in Bitcoin as Dollar Reserve Hits $4B", "Decrypt")

    assert [i.id for i in _dedupe([tree, desk])] == ["a"]


def test_different_stories_from_the_same_desk_both_survive():
    first = _item("a", "DECRYPT: Strategy Sells $105M in Bitcoin", "Tree of Alpha · DECRYPT")
    second = _item("b", "DECRYPT: Ethereum Foundation Moves 10,000 ETH", "Tree of Alpha · DECRYPT")

    assert len(_dedupe([first, second])) == 2


def test_prefix_is_only_stripped_when_it_names_the_items_own_desk():
    """A colon in an ordinary headline is not a desk prefix."""
    tweet = _item("a", "BREAKING: Strategy Sells $105M in Bitcoin", "Tree of Alpha · Twitter")
    desk = _item("b", "Strategy Sells $105M in Bitcoin", "Decrypt")

    assert len(_dedupe([tweet, desk])) == 2


def test_the_is_an_acronym_unless_cashtagged():
    assert is_uncashtagged_acronym("THE", "THE BLOCK: Crypto firms urge SEC to speed ETF reviews")
    assert not is_uncashtagged_acronym("THE", "$THE rallies 40% after Binance listing")


def test_tree_of_alpha_tag_on_a_desk_name_is_dropped():
    entry = {"symbols": ["THE_USDT"]}
    title = "THE INDEPENDENT: Hunter Biden launching crypto meme coin poking fun at laptop"

    assert asyncio.run(_treeofalpha_symbol(entry, title)) is None
