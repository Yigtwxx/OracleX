"""
The file-backed prompt templates must stay in sync with the code that renders them.

`render_prompt` only logs a warning when a `{{placeholder}}` survives
substitution, so a template that grows a placeholder its call site does not supply
would silently ship a half-filled prompt to the model. These tests make that
mismatch a test failure instead, in both directions: an unsupplied placeholder and
a supplied key the template never uses are equally wrong.
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

import pytest

from services.prompts import PROMPTS_DIR, load_prompt, render_prompt

BACKEND_DIR = Path(__file__).resolve().parent.parent
PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")

# Directories that hold code we did not write or do not ship.
SKIPPED_DIRS = {"venv", ".venv", "tests", "data", "__pycache__", ".pytest_cache", ".ruff_cache"}


def _template_names() -> List[str]:
    """Every template on disk, by the dotted-free name `load_prompt` expects."""
    return sorted(
        str(path.relative_to(PROMPTS_DIR).with_suffix("")) for path in PROMPTS_DIR.rglob("*.md")
    )


def _placeholders(name: str) -> Set[str]:
    return set(PLACEHOLDER_RE.findall(load_prompt(name)))


def _source_files() -> List[Path]:
    return [
        path
        for path in BACKEND_DIR.rglob("*.py")
        if not SKIPPED_DIRS.intersection(path.relative_to(BACKEND_DIR).parts)
    ]


def _call_sites() -> Tuple[List[Tuple[str, str, Set[str]]], List[Tuple[str, str]]]:
    """
    Find every `render_prompt` / `load_prompt` call with a literal template name.

    Returns (render_sites, load_sites) where a render site is
    ``(file, template_name, supplied_keys)`` and a load site is
    ``(file, template_name)``. Calls whose first argument is not a string literal
    are skipped — `render_prompt` forwards a variable to `load_prompt` internally.
    """
    render_sites: List[Tuple[str, str, Set[str]]] = []
    load_sites: List[Tuple[str, str]] = []

    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        where = str(path.relative_to(BACKEND_DIR))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            func = node.func
            fname = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if fname not in {"render_prompt", "load_prompt"}:
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            if not isinstance(node.args[0].value, str):
                continue

            template = node.args[0].value
            if fname == "render_prompt":
                keys = {kw.arg for kw in node.keywords if kw.arg is not None}
                render_sites.append((where, template, keys))
            else:
                load_sites.append((where, template))

    return render_sites, load_sites


RENDER_SITES, LOAD_SITES = _call_sites()
TEMPLATE_NAMES = _template_names()


def test_prompts_dir_contains_templates():
    assert TEMPLATE_NAMES, f"No .md templates found under {PROMPTS_DIR}"


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_load_prompt_every_template_reads_successfully(name):
    assert load_prompt(name).strip(), f"Template '{name}' is empty"


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_load_prompt_template_is_referenced_by_code(name):
    referenced = {t for _, t, _ in RENDER_SITES} | {t for _, t in LOAD_SITES}
    assert name in referenced, (
        f"Template '{name}' is not referenced by any render_prompt/load_prompt call — "
        "it is either dead or the call site uses a name that does not match the file"
    )


@pytest.mark.parametrize(
    ("where", "template", "supplied"),
    RENDER_SITES,
    ids=[f"{w}:{t}" for w, t, _ in RENDER_SITES],
)
def test_render_prompt_supplied_keys_match_template_placeholders(where, template, supplied):
    expected = _placeholders(template)
    missing, extra = expected - supplied, supplied - expected
    assert not missing, f"{where} renders '{template}' without {sorted(missing)}"
    assert not extra, f"{where} passes {sorted(extra)} to '{template}', which does not use them"


@pytest.mark.parametrize(("where", "template"), LOAD_SITES, ids=[f"{w}:{t}" for w, t in LOAD_SITES])
def test_load_prompt_template_has_no_placeholders(where, template):
    found = _placeholders(template)
    assert not found, (
        f"{where} loads '{template}' raw, but it declares {sorted(found)} — "
        "use render_prompt, or the markers reach the model verbatim"
    )


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_render_prompt_substitutes_every_placeholder(name):
    values: Dict[str, str] = {key: f"<{key}>" for key in _placeholders(name)}
    rendered = render_prompt(name, **values)
    assert "{{" not in rendered, f"Template '{name}' still has unsubstituted markers after render"
