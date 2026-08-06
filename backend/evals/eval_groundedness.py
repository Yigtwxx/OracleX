#!/usr/bin/env python3
"""
Measure how many figures in an answer are actually in its context.

This is the direct metric for the complaint that started this work: answers
stating prices, levels and percentages that no feed supplied. Every prompt in
the tree says "every number you write must appear in the context" — nothing
checked whether that held.

Method: run real chat turns, capture the exact context the model was given, pull
every number out of the answer, and look for each one in that context. A number
that is not there was invented.

The check is deliberately generous, because a false alarm here is worse than a
miss — it would send someone hunting a bug that isn't there:

  * Formatting is normalised, so `104,230.55` in the answer matches `104230.55`
    in the context.
  * Small integers (years, counts, list positions, "the two figures") are
    ignored — they are prose, not claims about market data.
  * A rounded figure counts as grounded when the context holds a number it could
    have been rounded from.

So the number this prints is a floor. Real hallucination is at least this bad.

Usage:
    python evals/eval_groundedness.py                  # every case
    python evals/eval_groundedness.py --limit 3        # a quick pass
    python evals/eval_groundedness.py --style concise
    python evals/eval_groundedness.py -v               # show each ungrounded figure

Needs a running Ollama and live market feeds — this makes real calls and is slow.
"""

import argparse
import asyncio
import os
import re
import sys
from typing import Dict, List, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Questions chosen to invite invention: each asks for specific figures, and some
# ask for things the feeds may not carry at all — which is where a model that
# fills gaps rather than reporting them gives itself away.
QUESTIONS = [
    "What is bitcoin trading at, and what are the levels that matter?",
    "Is ETH strong here? Give me the levels.",
    "BTC şu an nerede, hangi seviyeler önemli?",
    "How is market breadth looking, and what does it imply for positioning?",
    "What does the derivatives positioning say about leverage right now?",
    "Which assets are the biggest movers today and by how much?",
    "What is the Fear & Greed reading and how has it moved this week?",
    "Give me a read on equities versus crypto right now.",
    "What are the three most important headlines and why do they matter?",
    "Where would you say the risk is concentrated at the moment?",
]

# Below this, a bare number is prose rather than a market figure: years, ranks,
# "the two signals", horizon days. Market data — prices, market caps, index
# levels — sits above it, and percentages are checked separately.
SMALL_NUMBER_CEILING = 32

_NUMBER = re.compile(r"\d[\d,\s]*\.?\d*")


def _normalise(raw: str) -> str:
    return raw.replace(",", "").replace(" ", "").rstrip(".")


def _numbers_in(text: str) -> Set[str]:
    found = set()
    for match in _NUMBER.findall(text or ""):
        cleaned = _normalise(match)
        if not cleaned or cleaned == ".":
            continue
        try:
            value = float(cleaned)
        except ValueError:
            continue
        if abs(value) < SMALL_NUMBER_CEILING and value == int(value):
            continue
        found.add(cleaned)
    return found


def _is_grounded(number: str, context_numbers: Set[str], context: str) -> bool:
    """Whether `number` appears in the context, allowing for rounding."""
    if number in context_numbers or number in context:
        return True

    try:
        value = float(number)
    except ValueError:
        return True  # unparseable: not a claim we can judge

    # A figure the model rounded is still grounded — "$104.2K" from 104230.55.
    for candidate in context_numbers:
        try:
            other = float(candidate)
        except ValueError:
            continue
        if other == 0:
            continue
        if abs(value - other) / abs(other) < 0.005:
            return True
    return False


async def _run_case(question: str, style: str) -> Tuple[str, str]:
    """Answer one question and return (answer, the exact context it was given)."""
    from services import chat_service

    captured: Dict[str, str] = {}
    original = chat_service.render_prompt

    def _capture(name: str, **values):
        rendered = original(name, **values)
        if name == "chat/turn":
            captured["context"] = rendered
        return rendered

    chat_service.render_prompt = _capture
    try:
        result = await chat_service.chat_with_oracle(question, style=style)
    finally:
        chat_service.render_prompt = original

    return result.get("response", ""), captured.get("context", "")


async def main_async(args) -> int:
    questions = QUESTIONS[: args.limit] if args.limit else QUESTIONS

    total_numbers = 0
    total_ungrounded = 0
    per_case: List[Tuple[str, int, int]] = []

    for index, question in enumerate(questions, 1):
        print(f"[{index}/{len(questions)}] {question}")
        try:
            answer, context = await _run_case(question, args.style)
        except Exception as e:  # noqa: BLE001 — one bad turn should not end the run
            print(f"    failed: {e}\n")
            continue

        if not context:
            print("    no context captured — skipping\n")
            continue

        context_numbers = _numbers_in(context)
        answer_numbers = _numbers_in(answer)
        ungrounded = [n for n in answer_numbers if not _is_grounded(n, context_numbers, context)]

        total_numbers += len(answer_numbers)
        total_ungrounded += len(ungrounded)
        per_case.append((question, len(answer_numbers), len(ungrounded)))

        rate = len(ungrounded) / len(answer_numbers) if answer_numbers else 0.0
        print(f"    {len(answer_numbers)} figures, {len(ungrounded)} ungrounded ({rate:.0%})")
        if ungrounded and args.verbose:
            print(f"    ungrounded: {sorted(ungrounded)[:12]}")
            for number in sorted(ungrounded)[:3]:
                where = answer.find(number.split(".")[0])
                if where >= 0:
                    print(f"      …{answer[max(0, where - 60) : where + 60]}…")
        print()

    print("═" * 60)
    if not total_numbers:
        print("No figures were produced — nothing to judge.")
        return 0

    print(f"Figures in answers      {total_numbers}")
    print(f"Not found in context    {total_ungrounded}")
    print(f"Ungrounded rate         {total_ungrounded / total_numbers:.1%}")
    print(
        "\nThis is a floor, not a measurement of the true rate: rounding is "
        "forgiven,\nsmall integers are skipped, and a number matching any figure "
        "anywhere in\nthe context counts as grounded even if it was used to mean "
        "something else."
    )

    worst = sorted(per_case, key=lambda c: -c[2])[:3]
    if worst and worst[0][2]:
        print("\nWorst cases:")
        for question, count, bad in worst:
            if bad:
                print(f"  {bad}/{count}  {question}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="only run the first N questions")
    parser.add_argument("--style", default="detailed", choices=("concise", "detailed"))
    parser.add_argument("-v", "--verbose", action="store_true", help="show ungrounded figures")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
