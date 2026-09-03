"""
The memo's facts contract: every placeholder the template asks for is rendered,
from rounded facts, and nothing volatile leaks into the fingerprint unrounded.
"""

import re

from services.bist.radar.memo import MEMO_SPEC, memo_facts, memo_values
from services.prompts import load_prompt

PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def _candidate(**overrides) -> dict:
    base = {
        "ticker": "THYAO",
        "name": "TÜRK HAVA YOLLARI",
        "sector": "Taşımacılık",
        "sector_class": "industrial",
        "score_total": 73,
        "score_technical": 81,
        "score_fundamental": 62,
        "fundamental_depth": "full",
        "pe": 3.64,
        "pb": 0.4,
        "levels": {
            "pullback_pct": 0.0713,
            "rsi": 44.7,
            "structure": "higher",
            "zone_source": "support_zone",
            "zone_touches": 4,
            "volume_ratio": 0.83,
            "rr": 2.41,
            "range_position": 0.63,
        },
        "fundamentals": {
            "roe": 0.1266,
            "real_revenue_growth": 0.041,
            "real_profit_growth": -0.02,
            "net_debt_ebitda": 3.1,
            "short_debt_share": 0.2048,
            "loss_quarters": 1,
            "cash_conversion": 1.3,
            "inflation": 0.33,
        },
        "street": {"gap_pct": 0.464, "analysts": 11, "mark": 1.27},
        "flags": [{"key": "quiet_pullback", "label": "x"}],
        "kap_checked": True,
    }
    base.update(overrides)
    return base


def test_values_fill_every_placeholder_in_the_template():
    template = load_prompt(MEMO_SPEC.prompt)
    wanted = set(PLACEHOLDER_RE.findall(template)) - {"rules"}
    values = memo_values(memo_facts(_candidate(), "Swing (1-4 hafta)"))
    assert wanted == set(values)


def test_scores_are_quantized_so_a_point_of_drift_keeps_the_memo():
    a = memo_facts(_candidate(score_total=73), "Swing")
    b = memo_facts(_candidate(score_total=74), "Swing")
    assert a == b


def test_missing_statements_are_stated_not_filled_in():
    candidate = _candidate(fundamental_depth="ratios_only", fundamentals={"roe": None})
    text = memo_values(memo_facts(candidate, "Swing"))["fundamentals"]
    assert "unverified" in text
    assert "not available" in text


def test_flags_travel_as_keys_not_labels():
    facts = memo_facts(_candidate(flags=[{"key": "earnings_soon", "label": "Bilanço"}]), "Swing")
    assert facts["flags"] == ["earnings_soon"]
