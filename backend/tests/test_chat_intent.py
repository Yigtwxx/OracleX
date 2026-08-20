"""
The intent classifier, which decides both what a turn looks up and what it is
allowed to assert.

The cases below are not a sample: each one is a question shape that used to be
answered wrongly, or a near-miss that a looser rule would break. The Turkish
rows carry equal weight with the English ones — the product is used in both, and
a table that covers one is a feature that works for half the users.
"""

import pytest

from services import chat_intent


@pytest.mark.parametrize(
    ("message", "symbols", "expected"),
    [
        # Definitional — the whole reason this module exists. None of these
        # resolve an asset, so before the classifier they produced no evidence
        # and the answer was a refusal.
        ("funding rate nedir?", 0, "conceptual"),
        ("bear flag ne demek", 0, "conceptual"),
        ("RSI nasıl hesaplanır", 0, "conceptual"),
        ("what is a funding rate", 0, "conceptual"),
        ("explain 13F filings", 0, "conceptual"),
        ("what does open interest mean", 0, "conceptual"),
        ("difference between spot and perp", 0, "conceptual"),
        # …but a definitional phrasing that points at now is about now.
        ("what is BTC doing right now", 1, "current_state"),
        ("BTC şu an ne durumda", 1, "current_state"),
        # Causality outranks the topical rows: the derivatives data is the
        # evidence for "why did funding spike", not the answer to it.
        ("neden SOL düştü", 1, "causal"),
        ("why is funding so high", 1, "causal"),
        ("BTC'ye ne oldu", 1, "causal"),
        # Comparison needs two assets, not just comparative phrasing.
        ("BTC vs ETH hangisi daha iyi", 2, "comparative"),
        ("compare it to last month", 1, "current_state"),
        # Hypotheticals are checked before the topical rows.
        ("eğer ETF reddedilirse ne olur", 1, "scenario"),
        ("what if the fed cuts rates", 0, "scenario"),
        # Greetings, including Turkish suffixes on the stem.
        ("selam", 0, "greeting"),
        ("teşekkürler", 0, "greeting"),
        ("sağolun", 0, "greeting"),
        ("ok", 0, "greeting"),
        # An acknowledgement that carries a real question is not a greeting.
        ("teşekkürler, peki neden BTC düştü", 1, "causal"),
        # Topical rows.
        ("bugün ne kaçırdım", 0, "briefing"),
        ("funding oranları nerede", 1, "derivatives"),
        ("likidasyon seviyeleri", 1, "derivatives"),
        ("13F dosyalarında ne var", 1, "ownership"),
        ("izleme listemdeki coinler nasıl", 0, "portfolio"),
        ("NVDA hakkında son haberler", 1, "news"),
        # Macro only without an asset — "how is gold affecting BTC" is a
        # question about BTC's backdrop, which current_state already covers.
        ("dolar endeksi nasıl", 0, "macro"),
        ("altın BTC'yi nasıl etkiliyor", 1, "current_state"),
        # The default.
        ("BTC nasıl?", 1, "current_state"),
        ("", 0, "greeting"),
    ],
)
def test_classification(message, symbols, expected):
    assert chat_intent.classify(message, symbol_count=symbols) == expected


def test_every_classification_is_a_declared_intent():
    """A label the taxonomy does not carry would silently miss its answer mode."""
    samples = [
        "funding rate nedir",
        "BTC nasıl",
        "neden düştü",
        "selam",
        "bugün ne kaçırdım",
        "",
    ]
    for message in samples:
        assert chat_intent.classify(message) in chat_intent.INTENTS


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("current_state", "current_state"),
        ("Current State", "current_state"),
        ("  conceptual  ", "conceptual"),
        ("state", None),
        ("", None),
        (None, None),
        (42, None),
    ],
)
def test_a_model_supplied_intent_is_validated_not_trusted(raw, expected):
    assert chat_intent.coerce(raw) == expected


def test_an_unknown_label_returns_none_rather_than_a_default():
    """
    The caller already holds a deterministic classification. Replacing it with a
    fallback would trade a real signal for a made-up one.
    """
    assert chat_intent.coerce("please_do_whatever") is None


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("peki ETH?", True),
        ("ya SOL", True),
        ("bir de AVAX", True),
        ("what about ETH", True),
        ("and ETH", True),
        ("ETH nasıl?", False),
        ("pekişmiş bir trend", False),
    ],
)
def test_additive_openers(message, expected):
    assert chat_intent.is_additive(message) is expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("4 saatlik grafik", "4h"),
        ("1 saatlik", "1h"),
        ("günlük ne diyor", "1d"),
        ("haftalık kapanış", "1w"),
        ("15dk", "15m"),
        ("show me the hourly", "1h"),
        ("weekly chart", "1w"),
        ("BTC nasıl", None),
    ],
)
def test_timeframe_extraction(message, expected):
    assert chat_intent.timeframe_in(message) == expected


def test_the_longest_timeframe_phrase_wins():
    """ "4 saatlik" must not be read as "saatlik" and answered on the 1h chart."""
    assert chat_intent.timeframe_in("4 saatlik grafik nasıl") == "4h"


@pytest.mark.parametrize(
    "message",
    ["piyasa nasıl", "how is the market", "altcoinler ne durumda", "overall breadth"],
)
def test_market_wide_questions_are_recognised(message):
    assert chat_intent.is_market_wide(message)


def test_focus_clearing_intents_are_all_declared():
    assert chat_intent.FOCUS_CLEARING_INTENTS <= set(chat_intent.INTENTS)


def test_the_module_makes_no_llm_call_and_does_not_import_the_registry():
    """
    The dependency has to run one way: `chat_tools` imports these tables, not the
    other way round. A classifier that needed the tool registry could not be
    used to decide what the registry should offer.
    """
    source = (chat_intent.__file__ or "").replace(".pyc", ".py")
    with open(source, encoding="utf-8") as handle:
        imports = [line.strip() for line in handle if line.startswith(("import ", "from "))]
    assert imports == ["import re", "from typing import Optional, Tuple"], imports
