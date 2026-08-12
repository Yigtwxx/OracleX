"""
Prompt budgeting: token estimation and priority-ordered trimming.

The estimator has no ground truth available offline, so the two calibration
tests below pin it against real `prompt_eval_count` values measured against
qwen3.6:35b-a3b. Those numbers are the whole reason the estimator splits
characters by class instead of using one ratio — prose and market tables
tokenize almost 3.4x apart.

If a future model changes the tokenizer, these tests should fail. That is the
point: re-measure and re-calibrate rather than letting the budget drift.
"""

from services.prompt_budget import Block, estimate_tokens, fit

# Measured: 400 repetitions of this sentence plus a short needle and question
# evaluated to 4856 prompt tokens. The needle and question account for ~15.
_PROSE_SENTENCE = "Bitcoin traded in a range while liquidity thinned across venues. "
_PROSE_REPS = 400
_PROSE_ACTUAL_TOKENS = 4841

# Measured: 600 rows of this shape evaluated to 24545 prompt tokens. This is the
# shape that matters — a rendered market snapshot is nothing but rows like it.
_TABLE_ROW = "Row {i}: BTC 104{d}23.55 USD, funding 0.0{d}%, OI 41.{d}B, breadth {b}%.\n"
_TABLE_REPS = 600
_TABLE_ACTUAL_TOKENS = 24545


def _prose() -> str:
    return _PROSE_SENTENCE * _PROSE_REPS


def _table() -> str:
    return "".join(_TABLE_ROW.format(i=i, d=i % 9, b=30 + i % 40) for i in range(_TABLE_REPS))


def test_estimator_matches_measured_numeric_text():
    """
    Numeric text must be estimated closely, because that is what the snapshot is.

    An under-estimate here is the dangerous failure: the prompt would be built
    believing it fits, the server would truncate from the front, and the rules
    would be gone with nothing in the response to say so.
    """
    estimate = estimate_tokens(_table())
    ratio = estimate / _TABLE_ACTUAL_TOKENS
    assert 1.0 <= ratio <= 1.20, (
        f"numeric estimate {estimate} vs measured {_TABLE_ACTUAL_TOKENS} "
        f"(ratio {ratio:.2f}) — must not under-count, and 20% over is the ceiling"
    )


def test_estimator_over_counts_prose_rather_than_under_counting():
    """Prose may be over-counted; the cost is a trimmed history, which is cheap."""
    estimate = estimate_tokens(_prose())
    assert estimate >= _PROSE_ACTUAL_TOKENS
    # But not so far off that ordinary conversation gets thrown away for nothing.
    assert estimate <= 2.0 * _PROSE_ACTUAL_TOKENS


def test_empty_text_costs_nothing_and_short_text_is_never_free():
    assert estimate_tokens("") == 0
    assert estimate_tokens("x") >= 1


def test_blocks_within_budget_are_returned_untouched():
    blocks = [Block("a", "alpha", priority=10), Block("b", "beta", priority=20)]
    result = fit(blocks, budget_tokens=10_000)
    assert result.fits
    assert result.blocks == {"a": "alpha", "b": "beta"}
    assert not result.trimmed and not result.dropped


def test_lowest_priority_block_is_sacrificed_first():
    blocks = [
        Block("keep", "K" * 4000, priority=90),
        Block("expendable", "E" * 4000, priority=10),
    ]
    result = fit(blocks, budget_tokens=1500)
    assert "expendable" in result.dropped + result.trimmed
    assert result.blocks["keep"] == "K" * 4000


def test_pinned_blocks_are_never_trimmed_even_when_over_budget():
    """
    A prompt that fits but has lost its rules is worse than one that overflows.

    The rules and the user's own question are pinned; if they alone blow the
    budget the caller gets `fits == False` and a warning, not a silent edit.
    """
    blocks = [
        Block("rules", "R" * 20_000, priority=100, pinned=True),
        Block("history", "H" * 4000, priority=10),
    ]
    result = fit(blocks, budget_tokens=500)
    assert result.blocks["rules"] == "R" * 20_000
    assert "history" in result.dropped
    assert not result.fits


def test_trimmed_block_says_it_was_trimmed():
    """
    Silent truncation is the bug this module exists to prevent.

    "the last four turns" and "the whole conversation" are different contexts;
    the model must not read a trimmed block as a complete one.
    """
    blocks = [
        Block("pinned", "P" * 500, priority=99, pinned=True),
        Block(
            "history",
            "old turn\n" * 2000,
            priority=10,
            trim_from="head",
            trim_note="[older turns dropped to fit]",
        ),
    ]
    result = fit(blocks, budget_tokens=800)
    survivor = result.blocks.get("history", "")
    assert survivor, "history should be trimmed, not dropped, at this budget"
    assert "[older turns dropped to fit]" in survivor


def test_conversation_keeps_its_most_recent_turns():
    """History trims from the head — the newest exchange is the one that matters."""
    history = "".join(f"turn {i}\n" for i in range(3000))
    blocks = [
        Block("pinned", "P" * 200, priority=99, pinned=True),
        Block("history", history, priority=10, trim_from="head"),
    ]
    result = fit(blocks, budget_tokens=900)
    survivor = result.blocks["history"]
    assert "turn 2999" in survivor
    assert "turn 0\n" not in survivor


def test_ranked_block_keeps_its_best_hits():
    """Retrieval output is best-first, so it trims from the tail."""
    hits = "".join(f"hit {i}\n" for i in range(3000))
    blocks = [
        Block("pinned", "P" * 200, priority=99, pinned=True),
        Block("rag", hits, priority=10, trim_from="tail"),
    ]
    result = fit(blocks, budget_tokens=900)
    survivor = result.blocks["rag"]
    assert "hit 0\n" in survivor
    assert "hit 2999" not in survivor
