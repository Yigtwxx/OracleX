#!/usr/bin/env python3
"""Generate the marketing surface's facts from the repository itself.

`/developers` states this repository's own numbers — how many operations the API
exposes, how many tools the MCP server registers, how many tests have to pass
before anything merges. Hand-maintained, those numbers are wrong within a
release. They already were: the frontend suite grew from 327 to 397 tests and
three separate documents went on claiming the MCP server exposes 26 tools long
after it exposed 30, because every one of those figures had been counted by eye.

So the page carries no hand-written numbers at all. Everything measurable is
emitted here, into a TypeScript module the page imports, and CI fails when the
committed file stops matching what the sources say.

Two rules the extraction follows, both learned from the figures that drifted:

* **Collect, never grep.** `grep -c 'def test_'` misses every `parametrize` and
  every `it.each`, which is exactly how 397 tests came to be reported as 327.
  The counts here come from the test runners' own collection.
* **Parse, never match.** The MCP tool list is read with `ast`, not a regex. A
  regex over `@server.tool()` works today and silently drops the first tool
  someone writes as `@server.tool(name="…")`.

Usage:
    python scripts/build_repo_facts.py            # regenerate the module
    python scripts/build_repo_facts.py --check    # fail if it is out of date
"""

from __future__ import annotations

import argparse
import ast
import difflib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

from _openapi import BACKEND, REPO_ROOT, load_spec

FRONTEND = REPO_ROOT / "frontend"
MCP_DIR = REPO_ROOT / "mcp-server"
MCP_SERVER = MCP_DIR / "oracle_x_mcp" / "server.py"
SKILL_ROOT = REPO_ROOT / "agent-skill"
TARGET = FRONTEND / "lib" / "generated" / "repo-facts.ts"

#: The verbs an operation can be declared under. `trace` and `head` are absent
#: because FastAPI does not route them here; if one ever appears it should show
#: up as an operation-count mismatch rather than be silently dropped.
HTTP_METHODS = ("get", "post", "put", "patch", "delete", "options")

#: `PRESETS` carries one entry that is not a provider: `custom` is the escape
#: hatch for a base URL you supply yourself. Counting it would inflate the
#: figure by exactly the kind of half-truth this generator exists to prevent.
NOT_A_PROVIDER = "custom"

HEADER = """\
// GENERATED FILE — do not edit by hand.
// Regenerate with: python scripts/build_repo_facts.py
//
// Every number the marketing pages state about this repository comes from here,
// measured from the sources rather than counted by eye. `--check` runs in CI, so
// a figure that stops being true fails the build instead of quietly ageing.
"""


# ── Reading the sources ─────────────────────────────────────────────────────


def read_version() -> str:
    """The single repository version, cross-checked everywhere it is mirrored.

    `backend/pyproject.toml` calls itself the source of truth and asks for the
    other copies to be bumped with it. That request is a comment, and a comment
    cannot fail a build. This turns it into one.
    """
    pyproject = tomllib.loads((BACKEND / "pyproject.toml").read_text())
    version = str(pyproject["project"]["version"])

    mirrors: dict[str, str] = {
        "frontend/package.json": json.loads((FRONTEND / "package.json").read_text())["version"],
        "mcp-server/oracle_x_mcp/server.py": _mcp_declared_version(),
    }
    for skill in ("oracle-x-api", "oracle-x-dev"):
        path = SKILL_ROOT / skill / "SKILL.md"
        mirrors[f"agent-skill/{skill}/SKILL.md"] = _frontmatter_version(path)

    disagreeing = sorted(name for name, found in mirrors.items() if found != version)
    if disagreeing:
        raise SystemExit(
            f"backend/pyproject.toml declares version {version}, but these "
            "disagree:\n  "
            + "\n  ".join(f"{name} says {mirrors[name]}" for name in disagreeing)
            + "\nOne version for the whole repository — bump them all or none."
        )
    return version


def _mcp_declared_version() -> str:
    """The `version=` handed to `MCPServer(...)`, read structurally."""
    tree = ast.parse(MCP_SERVER.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "MCPServer"):
            continue
        for keyword in node.keywords:
            if keyword.arg == "version" and isinstance(keyword.value, ast.Constant):
                return str(keyword.value.value)
    raise SystemExit(f"no MCPServer(version=...) call found in {MCP_SERVER}")


def _frontmatter_version(path: Path) -> str:
    match = re.search(r'^version:\s*"?([^"\n]+)"?\s*$', path.read_text(), re.MULTILINE)
    if not match:
        raise SystemExit(f"no `version:` in the frontmatter of {path}")
    return match.group(1).strip()


def read_api(spec: dict[str, Any]) -> dict[str, Any]:
    """Path, operation, auth and router counts from the schema itself."""
    paths = spec.get("paths", {})
    counts: dict[str, int] = {}
    authed = 0
    for operations in paths.values():
        for method, operation in operations.items():
            if method.lower() not in HTTP_METHODS:
                continue
            counts[method.upper()] = counts.get(method.upper(), 0) + 1
            if operation.get("security"):
                authed += 1

    # WebSocket routes carry no schema entry, so they are absent from everything
    # above and a generated client will not find them. The page says so, which
    # means the list has to be read rather than remembered.
    websockets = sorted(
        {
            match.group(1)
            for path in (BACKEND / "routers").glob("*.py")
            for match in re.finditer(r'@\w+\.websocket\(\s*["\']([^"\']+)["\']', path.read_text())
        }
    )
    if not websockets:
        raise SystemExit(
            "no @router.websocket(...) routes found in backend/routers/. The "
            "developers page claims the schema omits a live feed; if that "
            "stopped being true, remove the claim rather than the check."
        )

    routers = sorted(p.stem for p in (BACKEND / "routers").glob("*.py") if p.stem != "__init__")
    # Descending count, then name: the page draws these as bars, and a bar chart
    # whose rows are in dictionary order reads as unsorted rather than as ranked.
    methods = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return {
        "paths": len(paths),
        "operations": sum(counts.values()),
        "authRequired": authed,
        "routers": len(routers),
        "websockets": websockets,
        "methods": [{"method": m, "count": c} for m, c in methods],
    }


def read_mcp_tools() -> dict[str, Any]:
    """Every `@server.tool()` in the MCP server, bucketed by its banner comment.

    AST rather than a regex, and not as a matter of taste: a regex over the
    decorator line reads today's `@server.tool()` and would silently drop the
    first tool anyone writes as `@server.tool(name="…")` or defines inside a
    conditional. The grouping does need the raw text, because `ast` discards
    comments and the banners are comments.
    """
    source = MCP_SERVER.read_text()
    tree = ast.parse(source)

    tools: list[tuple[int, str]] = []
    for node in tree.body:
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "tool"
                and isinstance(target.value, ast.Name)
                and target.value.id == "server"
            ):
                tools.append((node.lineno, node.name))
                break

    banners: list[tuple[int, str]] = [
        (i + 1, match.group(1).strip())
        for i, line in enumerate(source.splitlines())
        if (match := re.match(r"^#\s*─+\s*(.+?)\s*─+$", line))
    ]
    if not banners:
        raise SystemExit(
            f"no `# ── Label ──` banner comments in {MCP_SERVER}; the tool list "
            "has nothing to be grouped by."
        )

    grouped: dict[str, list[str]] = {label: [] for _, label in banners}
    for lineno, name in tools:
        above = [label for banner_line, label in banners if banner_line < lineno]
        if not above:
            raise SystemExit(
                f"tool `{name}` (line {lineno}) sits above the first banner "
                f"comment in {MCP_SERVER}. Every tool has to fall under one."
            )
        grouped[above[-1]].append(name)

    if empty := [label for label, names in grouped.items() if not names]:
        raise SystemExit(
            "these banner comments in " + str(MCP_SERVER) + " have no tools "
            "under them: " + ", ".join(empty)
        )

    return {
        "total": len(tools),
        "groups": [{"label": label, "tools": grouped[label]} for _, label in banners],
    }


def read_skills() -> list[dict[str, Any]]:
    """What each AgentSkill ships, counted off the filesystem."""
    from build_agent_skill import BIST_GROUP_TITLES, ENDPOINT_GROUPS

    # The allowlist is split across two skills, so each one counts only its own
    # groups. Summing all of ENDPOINT_GROUPS here would report the API skill as
    # carrying the BIST endpoints it was deliberately relieved of.
    def _generated(name: str, groups: list) -> dict[str, Any]:
        root = SKILL_ROOT / name
        reference = root / "references" / "endpoints.md"
        return {
            "file": str(reference.relative_to(root)),
            "lines": len(reference.read_text().splitlines()),
            "endpoints": sum(len(entries) for _, _, entries in groups),
            "groups": len(groups),
        }

    generated = {
        "oracle-x-api": _generated(
            "oracle-x-api",
            [g for g in ENDPOINT_GROUPS if g[0] not in BIST_GROUP_TITLES],
        ),
        "oracle-x-bist": _generated(
            "oracle-x-bist",
            [g for g in ENDPOINT_GROUPS if g[0] in BIST_GROUP_TITLES],
        ),
    }

    skills: list[dict[str, Any]] = []
    for name in ("oracle-x-api", "oracle-x-bist", "oracle-x-dev"):
        root = SKILL_ROOT / name
        skills.append(
            {
                "name": name,
                "version": _frontmatter_version(root / "SKILL.md"),
                "references": len(list((root / "references").glob("*.md"))),
                "examples": len(list((root / "examples").glob("*.py")))
                if (root / "examples").is_dir()
                else 0,
                # The two market skills have a generated half; the dev skill
                # is judgement all the way down and there is nothing to derive.
                "generated": generated.get(name),
            }
        )
    return skills


def read_health() -> dict[str, Any]:
    """The health registry's categories, imported rather than parsed."""
    sys.path.insert(0, str(BACKEND))
    from services.health_registry import CATEGORIES

    rows = [
        {
            "key": category.key,
            "label": category.label,
            "critical": category.critical,
            "upstreams": len(category.providers),
        }
        for category in CATEGORIES
    ]
    return {
        "categories": len(rows),
        "critical": sum(1 for row in rows if row["critical"]),
        # Distinct names: an upstream serving two categories is still one
        # upstream, and counting it twice would overstate the surface.
        "upstreams": len({p for c in CATEGORIES for p in c.providers}),
        "rows": rows,
    }


def read_llm() -> dict[str, Any]:
    sys.path.insert(0, str(BACKEND))
    from services.llm.presets import PRESETS

    return {
        "presets": len([name for name in PRESETS if name != NOT_A_PROVIDER]),
        "adapters": sorted({preset.adapter for preset in PRESETS.values()}),
    }


# ── Counting tests ──────────────────────────────────────────────────────────


def _interpreter_for(cwd: Path) -> str:
    """The python that can import the suite under `cwd`.

    CI installs every dependency into one environment, so `sys.executable` is
    right there. A developer's machine is the awkward case: `mcp-server` is
    installed into its own `.venv` — the README tells you to — and collecting
    its tests from the backend's interpreter fails on `import mcp`. Preferring a
    local `.venv` when one exists makes the same command work in both places
    without the generator needing to be told which it is in.
    """
    local = cwd / ".venv" / "bin" / "python"
    return str(local) if local.exists() else sys.executable


def _collect_pytest(cwd: Path, label: str) -> dict[str, Any]:
    """Test and file counts from pytest's own collection.

    Two `-q` flags on purpose: `backend/pyproject.toml` already sets one through
    `addopts` and `mcp-server/pyproject.toml` does not, so passing them
    explicitly is what makes both suites print the same `path.py: N` format
    regardless of local config.
    """
    result = subprocess.run(
        [
            _interpreter_for(cwd),
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-q",
            "-p",
            "no:warnings",
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    matches = re.findall(r"^(\S+\.py): (\d+)$", result.stdout, re.MULTILINE)
    if not matches:
        raise SystemExit(
            f"pytest collected nothing in {cwd}.\n"
            f"stdout:\n{result.stdout[-2000:]}\nstderr:\n{result.stderr[-2000:]}"
        )
    return {
        "name": label,
        "tests": sum(int(count) for _, count in matches),
        "files": len(matches),
    }


def _collect_vitest() -> dict[str, Any]:
    """Test and file counts from vitest's own collection."""
    result = subprocess.run(
        ["npx", "vitest", "list", "--json"],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        check=False,
    )
    # `vitest list` prints its banner before the JSON on some versions, so the
    # array is located rather than assumed to start at byte zero.
    start = result.stdout.find("[")
    if start == -1:
        raise SystemExit(
            "vitest listed no tests.\n"
            f"stdout:\n{result.stdout[-2000:]}\nstderr:\n{result.stderr[-2000:]}"
        )
    entries = json.loads(result.stdout[start:])
    return {
        "name": "frontend",
        "tests": len(entries),
        "files": len({entry["file"] for entry in entries}),
    }


def read_tests() -> dict[str, Any]:
    suites = [
        _collect_pytest(BACKEND, "backend"),
        _collect_pytest(MCP_DIR, "mcp-server"),
        _collect_vitest(),
    ]
    return {"suites": suites, "total": sum(s["tests"] for s in suites)}


# ── Rendering ───────────────────────────────────────────────────────────────


def ts(value: Any, indent: int = 0) -> str:
    """Render a Python value as prettier-shaped TypeScript."""
    pad = "  " * indent
    inner = "  " * (indent + 1)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        items = ",\n".join(inner + ts(v, indent + 1) for v in value)
        return f"[\n{items},\n{pad}]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = ",\n".join(f"{inner}{k}: {ts(v, indent + 1)}" for k, v in value.items())
        return f"{{\n{items},\n{pad}}}"
    raise TypeError(f"cannot render {type(value)!r} as TypeScript")


def render() -> str:
    spec = load_spec()
    version = read_version()
    out = [
        HEADER.rstrip(),
        "",
        "export interface MethodCount {",
        "  readonly method: string;",
        "  readonly count: number;",
        "}",
        "",
        "export interface McpGroup {",
        "  readonly label: string;",
        "  readonly tools: readonly string[];",
        "}",
        "",
        "export interface HealthRow {",
        "  readonly key: string;",
        "  readonly label: string;",
        "  readonly critical: boolean;",
        "  readonly upstreams: number;",
        "}",
        "",
        "export interface TestSuite {",
        "  readonly name: string;",
        "  readonly tests: number;",
        "  readonly files: number;",
        "}",
        "",
        f"export const VERSION = {ts(version)};",
        "",
        f"export const API = {ts(read_api(spec))} as const;",
        "",
        f"export const MCP = {ts(read_mcp_tools())} as const;",
        "",
        f"export const SKILLS = {ts(read_skills())} as const;",
        "",
        f"export const HEALTH = {ts(read_health())} as const;",
        "",
        f"export const LLM = {ts(read_llm())} as const;",
        "",
        f"export const TESTS = {ts(read_tests())} as const;",
    ]
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the committed module is stale",
    )
    args = parser.parse_args()

    rendered = render()

    if args.check:
        current = TARGET.read_text() if TARGET.exists() else ""
        if current != rendered:
            diff = difflib.unified_diff(
                current.splitlines(keepends=True),
                rendered.splitlines(keepends=True),
                fromfile="committed",
                tofile="generated",
            )
            sys.stdout.writelines(diff)
            print(
                "\nmarketing facts are stale. Run: python scripts/build_repo_facts.py",
                file=sys.stderr,
            )
            return 1
        print("marketing facts are up to date")
        return 0

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(rendered)
    print(f"wrote {TARGET.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
