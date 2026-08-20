"""
The grounded-note engine.

Four properties carry the whole feature, and each is pinned here: identical facts
must reuse a note rather than pay for it again, concurrent readers must produce
one generation rather than N, a dead provider must not become a retry loop, and
nothing on this path may raise into a page that was rendering fine without it.

The model is stubbed everywhere. What it writes is not this module's problem;
whether it is asked at all is exactly this module's problem, so most assertions
here are call counts.
"""

import asyncio

import pytest

from services import ai_notes, analysis_jobs
from services.ai_notes import NoteSpec

SPEC = NoteSpec(kind="test_note", prompt="macro/regime", max_tokens=100, max_age_seconds=3600)

FACTS = {"label": "Risk-on", "score": 2}
VALUES = {
    "label": "Risk-on",
    "score": "2",
    "components": "- breadth",
    "context": "- none",
    "unavailable": "none",
    "not_measured": "rates",
    "staleness": "The board is current.",
}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """
    Disk and job state per test.

    The store path is monkeypatched on the module rather than the filesystem
    being redirected, which is how `test_ownership_snapshots.py` isolates the
    same kind of on-disk store.
    """
    monkeypatch.setattr(ai_notes, "STORE_FILE", str(tmp_path / "ai_notes.json"))
    ai_notes.reset_state()
    analysis_jobs._jobs.clear()
    yield
    ai_notes.reset_state()
    analysis_jobs._jobs.clear()


class _Stub:
    """A stand-in LLM that counts calls, records wiring, and can be told to fail."""

    def __init__(self):
        self.calls = 0
        self.reply = "The dollar fell and breadth held."
        self.extra = None
        self.prefer = "unset"

    async def generate(self, _prompt, **kwargs):
        self.calls += 1
        self.extra = kwargs.get("extra")
        self.prefer = kwargs.get("prefer")
        return self.reply


@pytest.fixture
def model(monkeypatch):
    """
    Replace the real provider chain.

    Patched as an attribute on the live `services.llm` module rather than by
    swapping the module in `sys.modules`: `_generate` does `from services import
    llm`, which reads the attribute off the package and would walk straight past
    a `sys.modules` entry — and straight into a real Ollama request.
    """
    from services import llm

    stub = _Stub()
    monkeypatch.setattr(llm, "generate", stub.generate)
    return stub


async def _settle():
    """Let every in-flight note job finish."""
    tasks = [job.task for job in analysis_jobs._jobs.values() if job.task]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_a_miss_answers_generating_without_holding_the_request(model):
    """
    A local model takes tens of seconds. The request must not wait for it, or a
    page load becomes a page hang.
    """
    result = await ai_notes.get_note(SPEC, FACTS, VALUES)
    assert result["status"] == ai_notes.STATUS_GENERATING
    assert result["note"] is None
    await _settle()


async def test_the_same_facts_are_written_once_and_then_served(model):
    await ai_notes.get_note(SPEC, FACTS, VALUES)
    await _settle()

    result = await ai_notes.get_note(SPEC, FACTS, VALUES)
    assert result["status"] == ai_notes.STATUS_READY
    assert result["note"] == "The dollar fell and breadth held."
    assert model.calls == 1, "A cache hit must not reach the model"


async def test_concurrent_readers_produce_one_generation(model):
    """
    Ten open browsers are ten polls, not ten Ollama runs. `analysis_jobs.start`
    dedups on (kind, key) and this is the assertion that it is wired to.
    """
    await asyncio.gather(*(ai_notes.get_note(SPEC, FACTS, VALUES) for _ in range(10)))
    await _settle()
    assert model.calls == 1


async def test_different_facts_are_a_different_note(model):
    await ai_notes.get_note(SPEC, FACTS, VALUES)
    await _settle()
    await ai_notes.get_note(SPEC, {**FACTS, "score": -2}, VALUES)
    await _settle()
    assert model.calls == 2


async def test_fact_key_order_is_not_part_of_the_fingerprint(model):
    """A dict is unordered; a fingerprint that disagreed would never hit."""
    assert ai_notes.fingerprint(SPEC, {"a": 1, "b": 2}) == ai_notes.fingerprint(
        SPEC, {"b": 2, "a": 1}
    )


async def test_editing_the_prompt_retires_the_note(model, monkeypatch):
    """
    The prompt is hashed by content, so tuning it invalidates every note written
    from the old wording rather than serving the old reasoning indefinitely.
    """
    before = ai_notes.fingerprint(SPEC, FACTS)

    from services import prompts

    monkeypatch.setattr(prompts, "load_prompt", lambda name: f"edited {name}")

    assert ai_notes.fingerprint(SPEC, FACTS) != before


async def test_ai_disabled_is_answered_without_a_job(model, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "USE_AI", False)

    result = await ai_notes.get_note(SPEC, FACTS, VALUES)
    assert result["status"] == ai_notes.STATUS_UNAVAILABLE
    assert result["reason"] == ai_notes.REASON_AI_DISABLED
    assert model.calls == 0
    assert not analysis_jobs._jobs


async def test_a_dead_provider_does_not_become_a_retry_loop(model):
    """
    The client polls while a note is generating. Without a cooldown every poll
    would miss the store, start a fresh run against a provider chain that is
    already known to be down, and miss again — turning a 3-second poll into a
    continuous generation attempt.
    """
    model.reply = ""

    await ai_notes.get_note(SPEC, FACTS, VALUES)
    await _settle()
    assert model.calls == 1

    result = await ai_notes.get_note(SPEC, FACTS, VALUES)
    assert result["status"] == ai_notes.STATUS_UNAVAILABLE
    assert result["reason"] == ai_notes.REASON_PROVIDER_UNAVAILABLE
    assert model.calls == 1, "The cooldown must suppress the retry, not just report it"


async def test_a_good_note_outranks_a_later_failure(model):
    """A failed refresh is not a reason to withdraw a note that is still true."""
    await ai_notes.get_note(SPEC, FACTS, VALUES)
    await _settle()

    ai_notes._record_failure(ai_notes.fingerprint(SPEC, FACTS))

    result = await ai_notes.get_note(SPEC, FACTS, VALUES)
    assert result["status"] == ai_notes.STATUS_READY


async def test_an_expired_note_is_served_while_its_replacement_is_written(model):
    """
    The facts have not changed, so the stored sentence is still accurate. Showing
    a shimmer over an accurate sentence would be a downgrade.
    """
    short = NoteSpec(kind="test_note", prompt="macro/regime", max_age_seconds=0)

    await ai_notes.get_note(short, FACTS, VALUES)
    await _settle()

    result = await ai_notes.get_note(short, FACTS, VALUES)
    assert result["status"] == ai_notes.STATUS_READY
    assert result["note"]


async def test_the_store_is_bounded(model, monkeypatch):
    """
    `news_analysis_store` never evicts, and this store must not inherit that: it
    is keyed on a market read that can flap all day.
    """
    monkeypatch.setattr(ai_notes, "MAX_ENTRIES_PER_KIND", 3)

    for score in range(6):
        await ai_notes.get_note(SPEC, {"score": score}, VALUES)
        await _settle()

    assert len(ai_notes._all()) == 3


async def test_the_context_window_is_sent_explicitly(model):
    """
    Ollama defaults to 4096 tokens and truncates from the FRONT, which deletes
    the system prompt and with it every rule forbidding an invented figure.
    `ai_service.generate_completion` is the one call site in this repo that omits
    `num_ctx`, which is why notes do not go through it.
    """
    from config import settings

    await ai_notes.get_note(SPEC, FACTS, VALUES)
    await _settle()

    assert model.extra["num_ctx"] == settings.LLM_NUM_CTX
    assert settings.LLM_NUM_CTX >= 8192


async def test_notes_always_use_the_server_chain(model):
    """
    One note is written per read and served to every visitor from cache. Routing
    generation through a signed-in user's own provider would bill one reader for
    every other reader's copy.
    """
    await ai_notes.get_note(SPEC, FACTS, VALUES)
    await _settle()
    assert model.prefer is None


def test_model_markup_is_stripped_to_prose():
    """The prompts forbid markdown; a small model emits it anyway."""
    raw = "```\n## Heading\n- The dollar fell.\n\n- Breadth held.\n```"
    assert ai_notes._clean(raw) == "Heading The dollar fell. Breadth held."


def test_a_runaway_answer_is_truncated():
    assert len(ai_notes._clean("word " * 5000)) <= ai_notes.MAX_NOTE_CHARS
