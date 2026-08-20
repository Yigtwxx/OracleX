#!/usr/bin/env python3
"""
Measure whether the model picks the right tools.

`CHAT_PLANNER_ENABLED` was off for a documented reason: a bad plan costs a whole
turn, and nobody had measured what the deployed model actually does with a tool
catalogue. Turning it on without a number would repeat that mistake in the other
direction — so this is the number.

Method: run the planner alone (no tools, no answer) against labelled questions
and check what it named. Two metrics, because they fail differently:

  * **Recall** — did the plan include the tool the question obviously needs?
    A miss here means the answer was written without the evidence it wanted.
  * **Precision** — did it avoid the tools the question obviously does not need?
    A miss here is thirty seconds of latency and prompt budget spent on noise.

Also reported: how often the planner produced nothing usable and the turn fell
back to `heuristic_plan`. A high fallback rate means the flag is on and doing
nothing, which is worse than off — it costs a call per turn for no effect.

Usage:
    python evals/eval_planner.py
    python evals/eval_planner.py -v          # show each plan

Needs a running LLM provider. Makes one short call per case, so it is much
faster than the other evals.
"""

import argparse
import asyncio
import os
import sys
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Each case is a question whose right answer is not a matter of taste. Where a
# reasonable planner could go either way, the tool is in neither list.
CASES: List[Dict] = [
    {
        "q": "What is a funding rate and how is it calculated?",
        "must_exclude": ["read_chart", "derivatives", "social_search", "asset_news"],
    },
    {"q": "Funding rate nedir?", "must_exclude": ["read_chart", "derivatives", "web_search"]},
    {"q": "How is BTC doing right now?", "must_include": ["asset_technicals"]},
    {"q": "BTC'nin 4 saatlik grafiği ne diyor?", "must_include": ["read_chart"]},
    {"q": "Show me the BTC hourly chart structure", "must_include": ["read_chart"]},
    {"q": "Why did SOL drop today?", "must_include": ["explain_price_move", "asset_news"]},
    {"q": "Neden ETH bugün düştü?", "must_include": ["explain_price_move", "asset_news"]},
    {
        "q": "What are people saying about ETH on reddit?",
        "must_include": ["social_search"],
    },
    {"q": "Is NVDA expensive at these levels?", "must_include": ["stock_fundamentals"]},
    {"q": "NVDA değerlemesi pahalı mı?", "must_include": ["stock_fundamentals"]},
    {
        "q": "What if the spot ETF is denied — what happens to BTC?",
        "must_include": ["simulate_scenario"],
    },
    {"q": "Compare BTC and ETH over the last month", "must_include": ["compare_assets"]},
    {"q": "Where is BTC funding and open interest?", "must_include": ["derivatives"]},
    {"q": "BTC likidasyon seviyeleri nerede?", "must_include": ["derivatives"]},
    {"q": "How is the dollar and gold looking?", "must_include": ["macro_board"]},
    {"q": "Dolar ve altın ne durumda?", "must_include": ["macro_board"]},
    {"q": "What did I miss overnight?", "must_include": ["market_brief"]},
    {"q": "Bugün ne kaçırdım?", "must_include": ["market_brief"]},
    {"q": "Who holds NVDA and what did they do last quarter?", "must_include": ["ownership"]},
    {"q": "What has Powell said about rates recently?", "must_include": ["market_voices"]},
    {
        "q": "Read this for me https://www.coindesk.com/markets/example",
        "must_include": ["read_url"],
    },
    {"q": "What is a bear flag?", "must_exclude": ["read_chart", "web_search", "social_search"]},
]

# Below this, turning the flag on is not paying for itself.
RECALL_THRESHOLD = 0.70
PRECISION_THRESHOLD = 0.90
FALLBACK_THRESHOLD = 0.25


async def _plan_for(question: str) -> Tuple[List[str], str]:
    from services import chat_focus, chat_planner

    state = await chat_focus.resolve_state(question, [])
    plan = await chat_planner.plan_turn(question, state.focus, intent=state.intent, history=None)
    return [step.tool for step in plan.steps], plan.source


async def main_async(args) -> int:
    cases = CASES[: args.limit] if args.limit else CASES

    recall_hits = recall_total = 0
    precision_hits = precision_total = 0
    fallbacks = 0
    ran = 0
    failures: List[str] = []

    for index, case in enumerate(cases, 1):
        question = case["q"]
        print(f"[{index}/{len(cases)}] {question}")
        try:
            tools, source = await _plan_for(question)
        except Exception as e:  # noqa: BLE001 — one bad case should not end the run
            print(f"    failed: {e}\n")
            continue

        ran += 1
        if source == "heuristic":
            fallbacks += 1

        wanted = case.get("must_include") or []
        unwanted = case.get("must_exclude") or []

        if wanted:
            recall_total += 1
            # Any one of the listed tools counts — several questions have more
            # than one defensible right answer and pinning to one would measure
            # taste rather than correctness.
            if any(tool in tools for tool in wanted):
                recall_hits += 1
            else:
                failures.append(f"missed {wanted} — planned {tools} — {question}")

        for tool in unwanted:
            precision_total += 1
            if tool not in tools:
                precision_hits += 1
            else:
                failures.append(f"planned {tool} needlessly — {question}")

        print(f"    [{source}] {tools}")
        if args.verbose:
            print(f"    want {wanted}, avoid {unwanted}")
        print()

    print("═" * 60)
    if not ran:
        print("No cases completed — nothing to judge.")
        return 1

    recall = recall_hits / recall_total if recall_total else 1.0
    precision = precision_hits / precision_total if precision_total else 1.0
    fallback_rate = fallbacks / ran

    print(f"Cases            {ran}")
    print(f"Recall           {recall:.0%}  (threshold {RECALL_THRESHOLD:.0%})")
    print(f"Precision        {precision:.0%}  (threshold {PRECISION_THRESHOLD:.0%})")
    print(f"Fell back        {fallback_rate:.0%}  (threshold {FALLBACK_THRESHOLD:.0%})")

    if failures:
        print("\nWhat went wrong:")
        for line in failures:
            print(f"  {line}")

    passed = (
        recall >= RECALL_THRESHOLD
        and precision >= PRECISION_THRESHOLD
        and fallback_rate <= FALLBACK_THRESHOLD
    )
    print(
        "\nPASS — the planner is worth having on."
        if passed
        else "\nFAIL — CHAT_PLANNER_ENABLED is not paying for itself on this model.\n"
        "Either tune prompts/chat/plan_system.md against what it actually emits,\n"
        "or set the flag back to False in config.py."
    )
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="only run the first N cases")
    parser.add_argument("-v", "--verbose", action="store_true", help="show what was expected")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
