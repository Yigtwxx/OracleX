"""
The report stages must not ship a model's reasoning as the report.

Stages 2, 3 and 4 each instruct the model to start at `## Executive Summary`.
Whether a model that reasons first *fences* that reasoning is model-specific:
Qwen emits `<think>` blocks, which the LLM client strips before the text ever
reaches here, while Mistral writes the same content as unfenced prose. Trimming
to the anchor the prompt already mandates covers both without the client having
to guess where untagged reasoning ends.
"""

from services.analysis_service import _trim_to_report


def test_untagged_reasoning_before_the_anchor_is_dropped():
    """The Mistral failure: a plain-prose scratchpad ahead of the report."""
    raw = (
        "Here's a thinking process:\n\n"
        "1. Analyze User Input: fact-check the draft against the snapshot.\n"
        "2. Check BTC price: $81,133 in the table, $81,130 in the header.\n\n"
        "## Executive Summary\n"
        "BTC trades at $81,133.\n"
    )

    trimmed = _trim_to_report(raw)

    assert trimmed.startswith("## Executive Summary")
    assert "thinking process" not in trimmed
    assert "BTC trades at $81,133." in trimmed


def test_a_compliant_report_is_returned_unchanged():
    raw = "## Executive Summary\nBTC trades at $81,133.\n\n## Scenarios\nBase 50%."
    assert _trim_to_report(raw) == raw.strip()


def test_text_without_the_anchor_is_left_intact():
    """
    A missing heading is a different failure with its own repair.

    `missing_headings` reports it and the restore stage rewrites it; silently
    returning an empty string here would hide the section loss instead.
    """
    raw = "## Summary\nThe model renamed the section."
    assert _trim_to_report(raw) == raw


def test_only_the_first_anchor_starts_the_report():
    """A later mention must not re-cut a report that already began correctly."""
    raw = "## Executive Summary\nFirst.\n\nLater the draft says ## Executive Summary again."
    assert _trim_to_report(raw).startswith("## Executive Summary\nFirst.")


def test_an_anchor_inside_a_sentence_is_not_a_heading():
    """The anchor is a line of its own, so prose mentioning it does not match."""
    raw = "The draft should open with ## Executive Summary but it does not."
    assert _trim_to_report(raw) == raw
