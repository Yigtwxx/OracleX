"""
File-backed prompt templates.

Prompts live under `backend/prompts/` as plain text rather than string literals
in the services that use them, so they can be reviewed and tuned without
touching code.

Placeholders use a ``{{name}}`` delimiter and are substituted by plain string
replacement. `str.format` and `string.Template` are both unusable here: rendered
market data is full of ``$`` (prices) and ``{}`` (JSON examples), which those
engines would try to interpret.
"""

import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# backend/services/prompts.py -> backend/prompts
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

_cache: Dict[str, str] = {}


def load_prompt(name: str) -> str:
    """
    Read a prompt template by dotted-free relative name, e.g. ``analysis/stage2_report``.

    The ``.md`` suffix is implied. Templates are cached after the first read.
    """
    cached = _cache.get(name)
    if cached is not None:
        return cached

    path = PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt template not found: {path}")

    text = path.read_text(encoding="utf-8")
    _cache[name] = text
    return text


def render_prompt(name: str, **values: Any) -> str:
    """
    Load a template and substitute its ``{{placeholder}}`` markers.

    Unknown placeholders left in the template are logged rather than raising —
    a half-substituted prompt still produces a usable report, whereas an
    exception would kill the whole run.
    """
    text = load_prompt(name)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", "" if value is None else str(value))

    if "{{" in text:
        logger.warning("Prompt '%s' still contains unsubstituted placeholders", name)

    return text
