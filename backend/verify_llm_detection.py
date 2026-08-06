"""
End-to-end check of news symbol attribution, against the real LLM and the real
exchange listings.

The unit tests in `tests/test_symbol_detection.py` fake both, so they prove the
logic. This proves the wiring: that a provider is reachable, that the listings
resolve, and that the two together attribute a headline to the asset it is
actually about — or to nothing, which is the right answer more often than not.

    python verify_llm_detection.py
"""

import asyncio
import os
import sys
import time
from typing import Optional

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.ai_service import check_ai_health  # noqa: E402
from services.symbol_detection_service import detect_symbol_smart  # noqa: E402

# (title, asset-type hint, expected symbol or None, why it is here)
CASES: list[tuple[str, str, Optional[str], str]] = [
    (
        "Bitcoin ($BTC) surges to new highs",
        "crypto",
        "*BTC*",
        "explicit cashtag — resolved without asking the model",
    ),
    (
        "Apple announced new Vision Pro features today",
        "stock",
        "NASDAQ:AAPL",
        "company named in prose",
    ),
    (
        "The social media giant Meta Platforms is facing new EU regulations",
        "stock",
        "NASDAQ:META",
        "company named indirectly",
    ),
    (
        "Pepe coin is trending again as meme volume returns",
        "crypto",
        "*PEPE*",
        "coin named in prose",
    ),
    (
        "Coinbase beats third-quarter earnings expectations",
        "crypto",
        "NASDAQ:COIN",
        "stock story on a crypto feed — the class must follow the asset",
    ),
    (
        "US inflation cools in June, easing pressure on the Fed",
        "crypto",
        None,
        "no asset — 'US' is also a token ticker",
    ),
    (
        "The Fed is not moving rates this month, minutes show",
        "crypto",
        None,
        "no asset — 'not' is also a token ticker",
    ),
    (
        "AI training data lawsuit hits chipmakers",
        "stock",
        None,
        "no single asset — 'AI' and 'Rain' are both asset names",
    ),
    (
        "Nasdaq closes lower as tech breadth narrows",
        "stock",
        None,
        "index-wide move, not a story about Nasdaq Inc.",
    ),
]


def _matches(actual: Optional[str], expected: Optional[str]) -> bool:
    """`*BTC*` means "any venue, as long as it is BTC"."""
    if expected is None or actual is None:
        return actual == expected
    if expected.startswith("*") and expected.endswith("*"):
        return expected.strip("*") in actual
    return actual == expected


async def run_verification() -> int:
    print("🔍 News symbol attribution — end-to-end check\n")

    if await check_ai_health():
        print("✅ An LLM provider is reachable\n")
    else:
        print("⚠️  No LLM provider is reachable — detection will use the")
        print("   name-matching fallback, and the 'no asset' cases below are")
        print("   the ones that matter most.\n")

    failures = 0
    for title, hint, expected, why in CASES:
        start = time.time()
        result = await detect_symbol_smart("", title, hint)
        elapsed = time.time() - start

        ok = _matches(result.symbol, expected)
        failures += not ok

        print(f"{'✅' if ok else '❌'} {title}")
        print(f"   {why}")
        print(
            f"   expected={expected}  got={result.symbol}  "
            f"type={result.asset_type}  confident={result.confident}  "
            f"({elapsed:.2f}s)"
        )
        print()

    print(f"{len(CASES) - failures}/{len(CASES)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run_verification()))
