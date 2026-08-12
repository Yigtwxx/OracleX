"""
Prompt assembly under a token ceiling.

Ollama truncates an over-long prompt from the FRONT, and `/api/generate` renders
the `system` field before anything else. An overflow therefore deletes the system
prompt first — for these prompts, the anti-hallucination rules. Nothing in the
response says it happened; the model simply answers without them.

So the prompt is budgeted here instead of being discovered at the server. Blocks
are assembled in priority order and the cheapest-to-lose ones are trimmed until
the whole thing fits. Trimming is never silent: a trimmed block carries a note
saying what was dropped, because "the last four turns" and "the whole
conversation" are different contexts and the model must not confuse them.

Token counts are estimated, not exact — there is no offline tokenizer for the
local model. `estimate_tokens` is calibrated to over-count prose and match
numeric text, which is the safe direction: market snapshots are almost entirely
numeric, and an over-estimate costs a trimmed history while an under-estimate
costs the system prompt. `OllamaProvider` logs the real `prompt_eval_count`, so
the estimate can be re-calibrated against production traffic rather than guessed.
"""

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Characters-per-token divisors, per character class.
#
# BPE tokenizes digits far more finely than letters: a price like "104023.55"
# costs roughly one token per digit group, while an English word costs about one
# per three or four characters. A single blended ratio is therefore wrong for
# both — measured against qwen3.6:35b-a3b, prose ran ~5.4 chars/token and a
# numeric market table ran ~1.6.
#
# Calibrated against those two measurements: the numeric case lands within ~1%,
# the prose case over-counts by ~60%. That asymmetry is deliberate.
_LETTER_DIVISOR = 3.2
_DIGIT_DIVISOR = 0.8
_SYMBOL_DIVISOR = 1.1
_SPACE_DIVISOR = 5.0

_LETTERS = re.compile(r"[^\W\d_]")
_DIGITS = re.compile(r"\d")
_SPACES = re.compile(r"\s")


def estimate_tokens(text: str) -> int:
    """
    Estimate the token cost of `text`, biased to over-count.

    Never returns less than 1 for non-empty input, so a block can't look free.
    """
    if not text:
        return 0
    letters = len(_LETTERS.findall(text))
    digits = len(_DIGITS.findall(text))
    spaces = len(_SPACES.findall(text))
    symbols = len(text) - letters - digits - spaces
    estimate = (
        letters / _LETTER_DIVISOR
        + digits / _DIGIT_DIVISOR
        + symbols / _SYMBOL_DIVISOR
        + spaces / _SPACE_DIVISOR
    )
    return max(1, int(estimate) + 1)


@dataclass(frozen=True)
class Block:
    """
    One labelled section of a prompt, with the terms on which it may be cut.

    `priority` orders survival, not layout: the block with the lowest priority is
    trimmed first, and the caller is free to render the survivors in any order.
    `pinned` blocks are never touched — the hard constraints and the user's own
    question belong there, since a prompt that fits but has lost its rules is
    worse than one that overflows.
    """

    name: str
    text: str
    priority: int
    pinned: bool = False
    # Which end to cut. Ranked content (retrieval hits, search results) is
    # best-first, so its tail goes; a conversation is oldest-first, so its head
    # goes and the recent turns survive.
    trim_from: str = "tail"
    # Below this many characters the block stops being worth keeping and is
    # dropped whole rather than left as an uninterpretable fragment.
    min_chars: int = 240
    # Rendered in place of what was cut, so the model is told the block is partial.
    trim_note: str = ""


@dataclass
class BudgetResult:
    """Outcome of a fit: the surviving text per block, and what it cost."""

    blocks: dict[str, str]
    estimated_tokens: int
    budget_tokens: int
    trimmed: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)

    @property
    def fits(self) -> bool:
        return self.estimated_tokens <= self.budget_tokens

    def text(self, name: str, default: str = "") -> str:
        return self.blocks.get(name, default)


def _cut(block: Block, keep_chars: int) -> str:
    """Cut `block` down to roughly `keep_chars`, from the configured end."""
    if keep_chars >= len(block.text):
        return block.text
    note = block.trim_note or "[…trimmed to fit the context window…]"
    if block.trim_from == "head":
        # Resume at a line boundary so the survivor doesn't open mid-sentence.
        tail = block.text[-keep_chars:]
        newline = tail.find("\n")
        if 0 <= newline < 400:
            tail = tail[newline + 1 :]
        return f"{note}\n{tail}"
    head = block.text[:keep_chars]
    newline = head.rfind("\n")
    if newline > keep_chars // 2:
        head = head[:newline]
    return f"{head}\n{note}"


def fit(blocks: list[Block], budget_tokens: int) -> BudgetResult:
    """
    Trim `blocks` until their combined estimate fits `budget_tokens`.

    Lowest priority is sacrificed first, and each block is trimmed toward its
    `min_chars` before the next one is touched — losing half the conversation is
    better than losing all of the retrieved precedent. A block that would end up
    below `min_chars` is dropped whole instead.

    Pinned blocks are counted but never cut. If they alone exceed the budget the
    result simply doesn't fit; that is a bug in the caller's prompt, not
    something to paper over by deleting the rules.
    """
    surviving = {b.name: b.text for b in blocks}
    total = sum(estimate_tokens(b.text) for b in blocks)
    trimmed: list[str] = []
    dropped: list[str] = []

    if total <= budget_tokens:
        return BudgetResult(surviving, total, budget_tokens)

    # Cheapest to lose first.
    for block in sorted(blocks, key=lambda b: b.priority):
        if total <= budget_tokens or block.pinned:
            continue
        current = estimate_tokens(block.text)
        excess = total - budget_tokens
        if current <= excess or len(block.text) <= block.min_chars:
            surviving.pop(block.name, None)
            dropped.append(block.name)
            total -= current
            continue
        # Convert the token overshoot back into characters at this block's own
        # measured density, then cut a little extra so rounding can't leave it
        # marginally over.
        density = len(block.text) / current
        keep = max(block.min_chars, int((current - excess) * density) - 200)
        cut = _cut(block, keep)
        surviving[block.name] = cut
        trimmed.append(block.name)
        total = total - current + estimate_tokens(cut)

    result = BudgetResult(surviving, total, budget_tokens, trimmed, dropped)
    if trimmed or dropped:
        logger.info(
            "Prompt budget: ~%d/%d tokens after trimming %s and dropping %s",
            total,
            budget_tokens,
            trimmed or "nothing",
            dropped or "nothing",
        )
    if not result.fits:
        logger.warning(
            "Prompt budget: ~%d tokens still exceeds the %d-token budget after "
            "trimming everything trimmable — pinned blocks alone are too large",
            total,
            budget_tokens,
        )
    return result
