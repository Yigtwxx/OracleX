#!/usr/bin/env python3
"""
Measure how often the chat refuses a question it should have answered.

This is the direct metric for the complaint that started this work: the
assistant declining finance questions — "I don't have data on that", "the feeds
did not return", "I cannot say" — when the question needed no market data in the
first place. "What is a funding rate" resolves no asset, so no asset tool runs,
so no evidence block is built, and the turn prompt's standing rule is that every
figure must appear in the context. A model reading that rule literally concludes
it has nothing admissible to say.

The fix is the `conceptual` answer mode plus the rewritten rules 1, 2 and 4 in
`prompts/chat/turn.md`. This is how you tell whether it worked.

Three things are measured, and only two of them are failures:

  * **Refusal** — the answer is mostly an apology for missing data. The rules
    are still reading as permission to stop. This is the regression this eval
    exists to catch.
  * **Fabrication** — the answer states a market figure that is nowhere in the
    context it was given. Relaxing rules 1 and 2 reopened the thing they exist
    to prevent, and this going above zero is a reason to revert rather than to
    tune.
  * **Drift** (reported, not failed) — the answer quotes a *grounded* current
    price in an answer to a question that needed none. The market snapshot is
    pinned on every turn, so those figures are really in the context; the
    `conceptual` mode asks the model not to reach for them. A few of these mean
    the mode string could be firmer. They are not a correctness problem.

A good run is 0% refusal and 0% fabrication. Zero refusals with fabrication
above zero has traded one bug for a worse one.

Usage:
    python evals/eval_refusal.py
    python evals/eval_refusal.py --style concise
    python evals/eval_refusal.py -v            # print each answer

Needs a running LLM provider — this makes real calls and is slow.
"""

import argparse
import asyncio
import os
import re
import sys
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Questions that are unambiguously about markets and unambiguously answerable
# without a single live figure. If the assistant cannot answer these, the
# problem is the rules, not the data.
CONCEPTUAL_QUESTIONS = [
    "Funding rate nedir, nasıl hesaplanır?",
    "What is a bear flag and how do you trade it?",
    "RSI nasıl hesaplanır ve 70 üstü ne anlama gelir?",
    "Explain what a 13F filing is and what it can and cannot tell you.",
    "Spot ile perpetual futures arasındaki fark ne?",
    "What does open interest measure, and why is it different from volume?",
    "Likidasyon nasıl olur, kaskad likidasyon ne demek?",
    "How does an ETF creation and redemption mechanism work?",
    "What is the difference between realised and implied volatility?",
    "Piyasa derinliği (order book depth) neyi gösterir?",
]

# Phrases that mean the assistant declined. Deliberately narrow: an answer that
# *mentions* missing data while still answering is correct behaviour under rule
# 4, so only language that stands in place of an answer counts.
REFUSAL_MARKERS = (
    "i cannot answer",
    "i can't answer",
    "i am unable to",
    "i'm unable to",
    "no data is available",
    "no data available",
    "i do not have access",
    "i don't have access",
    "unable to provide",
    "cannot provide an answer",
    "cevap veremiyorum",
    "cevap veremem",
    "bilgi bulunmamaktadır",
    "veri bulunmamaktadır",
    "veriye sahip değilim",
    "elimde veri yok",
    "yeterli veri yok",
)

# An answer is also a refusal if it is mostly apology. A conceptual answer that
# comes in under this is not an explanation of anything.
MIN_SUBSTANTIVE_WORDS = 40

# Figures that would be a claim about the present. A conceptual answer may carry
# a convention (8 hours, 0-100, 45 days) but not a price or a percentage move.
#
# The comma is the trap here. Turkish writes decimals with one — the funding
# convention is "0,01%" — so a pattern that treats any comma as a thousands
# separator reads a textbook constant as a market price. Grouping is therefore
# required to be in threes, which "0,01" is not.
_PRICE = re.compile(r"[$₺€]\s?\d{1,3}(?:,\d{3})+(?:\.\d+)?|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b")
_MOVE = re.compile(r"[+-]\s?\d+(?:\.\d+)?\s?%")


def _is_refusal(answer: str) -> bool:
    lowered = answer.lower()
    if any(marker in lowered for marker in REFUSAL_MARKERS):
        return True
    return len(answer.split()) < MIN_SUBSTANTIVE_WORDS


def _market_figures(answer: str) -> List[str]:
    """Figures in an answer that read as claims about the present."""
    return _PRICE.findall(answer) + _MOVE.findall(answer)


def _digits(raw: str) -> str:
    """A figure reduced to what it would look like in a data feed."""
    return re.sub(r"[^\d.]", "", raw)


def _is_grounded(figure: str, context: str) -> bool:
    """
    Whether this figure appears in the context the model was given.

    Deliberately generous — the strict version's false alarms would send someone
    hunting a fabrication that isn't one. A figure counts as grounded if its
    digits appear anywhere in the context, in any formatting.
    """
    digits = _digits(figure)
    if not digits:
        return True
    stripped = re.sub(r"[,\s]", "", context)
    return digits in stripped or digits.rstrip(".0") in stripped


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
    questions = CONCEPTUAL_QUESTIONS[: args.limit] if args.limit else CONCEPTUAL_QUESTIONS

    refusals: List[str] = []
    fabricated: List[Tuple[str, List[str]]] = []
    drifted: List[Tuple[str, List[str]]] = []
    answered = 0

    for index, question in enumerate(questions, 1):
        print(f"[{index}/{len(questions)}] {question}")
        try:
            answer, context = await _run_case(question, args.style)
        except Exception as e:  # noqa: BLE001 — one bad turn should not end the run
            print(f"    failed: {e}\n")
            continue

        answered += 1
        refused = _is_refusal(answer)
        figures = _market_figures(answer)
        invented = [f for f in figures if not _is_grounded(f, context)]
        grounded = [f for f in figures if _is_grounded(f, context)]

        if refused:
            refusals.append(question)
        if invented:
            fabricated.append((question, invented))
        if grounded:
            drifted.append((question, grounded))

        verdict = "REFUSED" if refused else "answered"
        notes = []
        if invented:
            notes.append(f"FABRICATED {invented[:4]}")
        if grounded:
            notes.append(f"drifted onto {len(grounded)} grounded figure(s)")
        suffix = f" — {'; '.join(notes)}" if notes else ""
        print(f"    {verdict} ({len(answer.split())} words){suffix}")
        if args.verbose:
            print(f"    {answer[:400]}\n")
        print()

    print("═" * 60)
    if not answered:
        print("No turns completed — nothing to judge.")
        return 1

    print(f"Questions asked   {answered}")
    print(f"Refused           {len(refusals)}  ({len(refusals) / answered:.0%})   ← the regression")
    print(
        f"Fabricated        {len(fabricated)}  ({len(fabricated) / answered:.0%})"
        "   ← worse than a refusal"
    )
    print(
        f"Drifted           {len(drifted)}  ({len(drifted) / answered:.0%})   (reported, not a failure)"
    )

    if refusals:
        print("\nRefused:")
        for question in refusals:
            print(f"  {question}")
    if fabricated:
        print("\nFabricated — figures found nowhere in the context:")
        for question, figs in fabricated:
            print(f"  {figs[:4]}  {question}")
    if drifted:
        print("\nDrifted — grounded figures quoted in an answer that needed none:")
        for question, figs in drifted:
            print(f"  {figs[:4]}  {question}")
        print(
            "  (The market snapshot is pinned on every turn, so these are real. "
            "The\n  conceptual mode asks the model not to reach for them; a "
            "steady stream here\n  means that string could be firmer.)"
        )

    print(
        "\nA good run is 0% refused and 0% fabricated. Zero refusals with "
        "fabrication\nabove zero is not progress — it means the rule relaxation "
        "reopened the thing\nrules 1 and 2 exist to prevent."
    )
    return 1 if (refusals or fabricated) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="only run the first N questions")
    parser.add_argument("--style", default="detailed", choices=("concise", "detailed"))
    parser.add_argument("-v", "--verbose", action="store_true", help="print each answer")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
