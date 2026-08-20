"""
Grounded one-paragraph notes for pages whose numbers are already correct.

The macro board, the chains board and the ownership board all render deterministic
figures and leave the reader to work out what they mean. These notes close that
gap without moving any arithmetic into the model: each caller computes its own
label, thresholds and deltas in Python and hands this engine a finished set of
facts, and the model's only job is to say what they mean in a sentence or two.

Three properties make that affordable on a local model:

* **Facts are the cache key.** A note is fingerprinted by the prompt it was
  written from and the facts it was written about. Identical facts reuse the
  note; a prompt edit retires every note derived from it, exactly as a prompt
  edit retires a stored news analysis.
* **Callers quantize.** The macro board changes every two minutes, so
  fingerprinting raw prices would regenerate a note every two minutes and the
  cache would never hit. Callers round their facts once, and — this is the part
  that matters for correctness — the text handed to the model must be rendered
  from those same rounded facts. A cached note can then never cite a figure that
  has since moved, because a moved figure is a different fingerprint.
* **Generation is single-flight and never blocks the request.** A local model
  takes tens of seconds. Ten open browsers must not become ten Ollama runs, and
  no HTTP request is held open waiting for one: a miss starts the run and answers
  "generating", and the caller polls.

Nothing here raises. A note is decoration on a page that is already complete, so
every failure — AI disabled, provider chain down, an empty completion — comes
back as `unavailable` and the page renders without it.
"""

import hashlib
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

STORE_FILE = "data/ai_notes.json"

# The hard constraints every note shares live in `prompts/notes/rules.md`. They
# are injected here rather than by each caller so a new note cannot be added
# without them, and every note prompt ends with `{{rules}}` rather than carrying
# them at the head: Ollama renders `system` first and truncates from the front, so
# constraints at the top of a prompt are the first thing an overflow deletes — and
# a model that has lost "every figure must appear in the input" writes a confident
# invented one.
#
# Spelled out at both use sites rather than held in a constant, because
# `test_prompts.py` scans for literal `load_prompt` arguments to prove no template
# is dead, and a variable there would hide this file from it.

# Bumped by hand when the *code* around the prompts changes in a way the prompt
# hashes would not catch — a different cleaner, a different set of placeholders.
NOTE_REVISION = "1"

# Notes retained per kind. Each surface has a small fingerprint space (a regime
# label, a set of flagged anomalies, a quarter's filings), so this is generous
# enough that a note survives a day of flapping and bounded enough that the file
# cannot grow without limit.
MAX_ENTRIES_PER_KIND = 40

# A hard ceiling on what is stored, independent of `max_tokens`. A model that
# ignores the length rule produces an essay; the page has room for a paragraph.
MAX_NOTE_CHARS = 900

# How long a failed generation is remembered. Without this a dead provider chain
# is a retry loop: every poll misses the store, starts a run, gets nothing back,
# and misses again. Held in memory rather than on disk on purpose — a restart is
# the most likely thing to have fixed the provider, so it should retry at once.
FAILURE_COOLDOWN_SECONDS = 300

STATUS_READY = "ready"
STATUS_GENERATING = "generating"
STATUS_UNAVAILABLE = "unavailable"

REASON_AI_DISABLED = "ai_disabled"
REASON_PROVIDER_UNAVAILABLE = "provider_unavailable"
REASON_INSUFFICIENT_DATA = "insufficient_data"
# Distinct from insufficient data: everything was measurable and nothing was
# unusual. A surface that says "quiet" is not a surface that failed.
REASON_NOTHING_FLAGGED = "nothing_flagged"

_lock = threading.Lock()
_entries: Optional[Dict[str, Dict[str, Any]]] = None
_failures: Dict[str, float] = {}


@dataclass(frozen=True)
class NoteSpec:
    """
    One kind of note: which prompt writes it, and how long it stays good.

    `max_age_seconds` is a backstop, not the primary cache control. The facts
    fingerprint already retires a note the moment the read changes; this only
    covers what the facts deliberately leave out — a note quantized to the day
    should not still be served a week later because nothing crossed a threshold.
    """

    kind: str
    prompt: str
    max_tokens: int = 220
    temperature: float = 0.2
    max_age_seconds: int = 6 * 3600


def _load_json(filepath: str, default: Any) -> Any:
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _save_json(filepath: str, data: Any) -> None:
    directory = os.path.dirname(filepath)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _all() -> Dict[str, Dict[str, Any]]:
    global _entries
    if _entries is None:
        _entries = _load_json(STORE_FILE, {})
    return _entries


def _canonical(facts: Dict[str, Any]) -> str:
    """
    The facts as one stable string.

    `sort_keys` is what makes this a fingerprint rather than a hash of dict
    ordering, and `default=str` keeps a stray date or Decimal from raising on a
    path whose whole point is that it cannot fail.
    """
    return json.dumps(facts, sort_keys=True, separators=(",", ":"), default=str)


def fingerprint(spec: NoteSpec, facts: Dict[str, Any]) -> str:
    """
    Short digest of everything that determines what this note says.

    The prompt template is hashed by content, not by name, so editing
    `macro/regime.md` retires every macro note without anyone remembering to
    bump a version. The model id is included because the same facts written by a
    different model are a different note.
    """
    from config import settings
    from services.prompts import load_prompt

    digest = hashlib.sha256()
    digest.update(NOTE_REVISION.encode())
    digest.update(spec.kind.encode())
    digest.update((settings.LLM_MODEL or "").encode())
    for name in (spec.prompt, "notes/rules"):
        try:
            digest.update(load_prompt(name).encode())
        except Exception as e:  # noqa: BLE001 — a missing prompt fails louder at render time
            logger.warning("Could not hash prompt %s for the note fingerprint: %s", name, e)
    digest.update(_canonical(facts).encode())
    return f"{spec.kind}:{digest.hexdigest()[:12]}"


# Markdown the prompts forbid but a small model emits anyway. Stripped rather
# than rejected: a good sentence wearing a bullet is still a good sentence.
_FENCE = re.compile(r"^\s*```[^\n]*\n|\n```\s*$")
_LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.MULTILINE)
_HEADING = re.compile(r"^\s*#{1,6}\s*", re.MULTILINE)
_BLANK_RUN = re.compile(r"\n{2,}")


def _clean(raw: str) -> str:
    """Model output as the plain prose the page expects, or "" if there is none."""
    text = _FENCE.sub("", raw or "").strip()
    text = _HEADING.sub("", text)
    text = _LIST_MARKER.sub("", text)
    # A note is one block of prose. Paragraph breaks in a two-sentence answer are
    # the model padding, not structure worth keeping.
    text = _BLANK_RUN.sub(" ", text)
    text = " ".join(text.split())
    return text[:MAX_NOTE_CHARS].strip()


def _stored(key: str) -> Optional[Dict[str, Any]]:
    with _lock:
        entry = _all().get(key)
        return dict(entry) if entry else None


def _put(key: str, spec: NoteSpec, note: str) -> None:
    with _lock:
        entries = _all()
        entries[key] = {
            "kind": spec.kind,
            "note": note,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        _prune(entries, spec.kind)
        _save_json(STORE_FILE, entries)


def _prune(entries: Dict[str, Dict[str, Any]], kind: str) -> None:
    """Drop the oldest notes of this kind past the cap. Caller holds the lock."""
    of_kind = [(k, v) for k, v in entries.items() if v.get("kind") == kind]
    if len(of_kind) <= MAX_ENTRIES_PER_KIND:
        return
    of_kind.sort(key=lambda item: item[1].get("generated_at") or "")
    for key, _ in of_kind[: len(of_kind) - MAX_ENTRIES_PER_KIND]:
        entries.pop(key, None)


def _record_failure(key: str) -> None:
    with _lock:
        _failures[key] = time.monotonic()


def _failed_recently(key: str) -> bool:
    with _lock:
        at = _failures.get(key)
        if at is None:
            return False
        if time.monotonic() - at < FAILURE_COOLDOWN_SECONDS:
            return True
        _failures.pop(key, None)
        return False


def _age_seconds(entry: Dict[str, Any]) -> Optional[float]:
    stamp = entry.get("generated_at")
    if not stamp:
        return None
    try:
        written = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if written.tzinfo is None:
        written = written.replace(tzinfo=UTC)
    return (datetime.now(UTC) - written).total_seconds()


def ready(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": STATUS_READY,
        "note": entry.get("note"),
        "generated_at": entry.get("generated_at"),
        "reason": None,
    }


def unavailable(reason: str) -> Dict[str, Any]:
    """The note contract for a surface that cannot have one right now."""
    return {"status": STATUS_UNAVAILABLE, "note": None, "generated_at": None, "reason": reason}


def generating() -> Dict[str, Any]:
    return {"status": STATUS_GENERATING, "note": None, "generated_at": None, "reason": None}


async def get_note(
    spec: NoteSpec,
    facts: Dict[str, Any],
    values: Dict[str, str],
) -> Dict[str, Any]:
    """
    The note for these facts: cached, being written, or unavailable.

    `facts` is the fingerprint — quantized, and small. `values` is what fills the
    prompt's ``{{placeholders}}``, and **must be rendered from `facts` alone**.
    Deriving it from anything fresher would let a cached note cite a figure that
    has since moved, which is the one failure this whole design exists to avoid.
    """
    from config import settings

    if not settings.USE_AI:
        return unavailable(REASON_AI_DISABLED)

    key = fingerprint(spec, facts)
    entry = _stored(key)

    # A recent failure outranks a miss but not a hit: if a good note is already
    # stored for these facts, a failed attempt to refresh it changes nothing the
    # reader should see.
    if _failed_recently(key) and not (entry and entry.get("note")):
        return unavailable(REASON_PROVIDER_UNAVAILABLE)

    if entry and entry.get("note"):
        age = _age_seconds(entry)
        if age is not None and age <= spec.max_age_seconds:
            return ready(entry)
        # Past its age but still about the current read, so it is served while a
        # replacement is written. Showing a spinner over an accurate sentence
        # would be a downgrade.
        await _start(spec, key, values)
        return ready(entry)

    await _start(spec, key, values)
    return generating()


async def _start(spec: NoteSpec, key: str, values: Dict[str, str]) -> None:
    """
    Take the single-flight lock for this fingerprint and write the note.

    `analysis_jobs` is imported here rather than at module scope because it
    imports `analysis_service` on the way up, and that reaches back into this
    layer — the same deferred-import workaround `news_analysis_service` uses.

    The job is only a lock. Its result is never read: the note goes to the store,
    which is where the next poll looks, and which survives a restart.
    """
    from services import analysis_jobs

    async def runner(_controls: Any) -> Dict[str, Any]:
        # A job that settled between this caller's lookup and its `start` would
        # otherwise be regenerated here — single-flight only dedups runs that
        # overlap, not one that just finished.
        existing = _stored(key)
        if existing and existing.get("note"):
            return {"note": existing["note"]}

        note = await _generate(spec, values)
        if note:
            _put(key, spec, note)
        else:
            _record_failure(key)
        return {"note": note}

    try:
        await analysis_jobs.start(key, analysis_jobs.KIND_NOTE, [], runner)
    except Exception as e:  # noqa: BLE001 — a note must not take a page down
        logger.warning("Could not start note generation for %s: %s", key, e)


async def _generate(spec: NoteSpec, values: Dict[str, str]) -> str:
    """Render the prompt, ask the model, and return clean prose or ""."""
    from config import settings
    from services import llm
    from services.prompts import load_prompt, render_prompt

    try:
        prompt = render_prompt(spec.prompt, rules=load_prompt("notes/rules"), **values)
        system_prompt = load_prompt("generic/system_default")
    except FileNotFoundError:
        logger.error("Note prompt %s is missing — no note can be written", spec.prompt)
        return ""

    try:
        raw = await llm.generate(
            prompt,
            system=system_prompt,
            temperature=spec.temperature,
            max_tokens=spec.max_tokens,
            timeout=120.0,
            reasoning=False,  # a two-sentence note has nothing to think about
            # Not optional, and the reason `ai_service.generate_completion` is
            # not used here: Ollama defaults to a 4096-token context and
            # truncates from the FRONT, which deletes the system prompt — every
            # rule forbidding an invented figure — without saying so. The news,
            # chat and report paths all pass this; `generate_completion` is the
            # one call site that does not, and a note must not inherit that.
            extra={"num_ctx": settings.LLM_NUM_CTX, "repeat_penalty": 1.1},
            # Always the server chain. One note is written per read and served to
            # every visitor from cache, so billing a signed-in user's own key for
            # text that anonymous readers then collect would be wrong.
            prefer=None,
        )
    except Exception as e:  # noqa: BLE001 — a note must not take a page down
        logger.warning("Note %s could not be generated: %s", spec.kind, e)
        return ""

    note = _clean(raw or "")
    if not note:
        logger.info("Note %s came back empty — the provider chain is unusable", spec.kind)
    return note


def reset_state() -> None:
    """Drop the in-memory view and any recorded failures. For tests."""
    global _entries
    with _lock:
        _entries = None
        _failures.clear()
