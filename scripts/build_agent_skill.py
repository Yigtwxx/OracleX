#!/usr/bin/env python3
"""Generate the agent skill's endpoint reference from the live FastAPI schema.

`agent-skill/oracle-x-api/SKILL.md` is written by hand — it carries the
judgement about which endpoint answers which question, and no generator can
produce that. What a generator *can* produce, and should, is the mechanical
half: paths, parameters, request bodies and auth requirements. Those live in
`references/endpoints.md`, and keeping them hand-written would guarantee the
skill drifts from the API within a release or two.

The schema is read by importing `create_app()` and calling `app.openapi()`, so
no server has to be running. Only the endpoints in `ENDPOINT_GROUPS` are
emitted: the terminal exposes ~120 operations, but most are the UI talking to
itself (profile, community, social, admin) and documenting them would cost the
agent context without buying it a capability.

Usage:
    python scripts/build_agent_skill.py            # regenerate the reference
    python scripts/build_agent_skill.py --check    # fail if it is out of date
    python scripts/build_agent_skill.py --zip      # also rebuild the .zip
"""

from __future__ import annotations

import argparse
import difflib
import sys
import zipfile
from pathlib import Path
from typing import Any

from _openapi import REPO_ROOT, load_spec

SKILL_DIR = REPO_ROOT / "agent-skill" / "oracle-x-api"
REFERENCE = SKILL_DIR / "references" / "endpoints.md"

# Distribution archives, one per skill. The API skill's filename predates the
# second skill and is linked from published release notes, so it keeps its name
# rather than gaining a suffix for symmetry.
ZIP_TARGETS: tuple[tuple[Path, Path], ...] = (
    (SKILL_DIR, REPO_ROOT / "agent-skill" / "Oracle-X-Skill.zip"),
    (
        REPO_ROOT / "agent-skill" / "oracle-x-dev",
        REPO_ROOT / "agent-skill" / "Oracle-X-Dev-Skill.zip",
    ),
)

# The allowlist, grouped the way the skill's decision table groups them. Order
# here is the order in the generated document, so a reader who scrolls sees the
# same taxonomy the SKILL.md taught them.
ENDPOINT_GROUPS: list[tuple[str, str, list[tuple[str, str]]]] = [
    (
        "Prices and market state",
        "Spot prices, index levels, candles and derived technical levels.",
        [
            ("GET", "/api/price/{symbol}"),
            ("GET", "/api/market-overview"),
            ("GET", "/api/market/indices"),
            ("GET", "/api/market/candles/{symbol}"),
            ("GET", "/api/technical/{symbol}"),
            ("GET", "/api/asset-detail/{symbol}"),
            ("GET", "/api/symbols"),
            ("GET", "/api/heatmap/data"),
            ("GET", "/api/fear-greed"),
        ],
    ),
    (
        "News and its analysis",
        "The feed, one article, and the LLM read of an article.",
        [
            ("GET", "/api/news"),
            ("GET", "/api/news/{news_id}"),
            ("GET", "/api/news/{news_id}/analysis"),
            ("POST", "/api/news/{news_id}/analysis/jobs"),
            ("GET", "/api/news/analysis/jobs/{job_id}"),
            ("POST", "/api/analyze"),
        ],
    ),
    (
        "Scheduled analysis reports",
        "The long-form daily/weekly reports the terminal generates on a timer.",
        [
            ("GET", "/api/analysis/reports"),
            ("GET", "/api/analysis/report/{timeframe}"),
            ("POST", "/api/analysis/jobs/{timeframe}"),
            ("GET", "/api/analysis/jobs/{job_id}"),
        ],
    ),
    (
        "Memory and retrieval (RAG)",
        "Historical context: what happened before, what resembles now.",
        [
            ("GET", "/api/rag/query"),
            ("GET", "/api/rag/insights/{symbol}"),
            ("GET", "/api/rag/compare/{symbol_a}/{symbol_b}"),
            ("GET", "/api/rag/daily-brief"),
            ("GET", "/api/rag/anomalies"),
            ("GET", "/api/rag/event-at-date"),
            ("POST", "/api/rag/news-similarity"),
            ("POST", "/api/rag/scenario"),
            ("GET", "/api/rag/stats"),
        ],
    ),
    (
        "Macro",
        "Cross-asset state: indices, metals, the regime label and its evidence.",
        [
            ("GET", "/api/macro/board"),
            ("GET", "/api/macro/elections"),
            ("GET", "/api/macro/regime"),
            ("GET", "/api/macro/pizza-index"),
            ("GET", "/api/macro/neh-index"),
        ],
    ),
    (
        "Chains",
        "Per-chain metrics and anomalies measured against each chain's baseline.",
        [
            ("GET", "/api/chains/board"),
            ("GET", "/api/chains/anomalies"),
        ],
    ),
    (
        "Derivatives and on-chain flow",
        "Liquidations, funding, and large-transaction flow.",
        [
            ("GET", "/api/home/liquidations"),
            ("GET", "/api/home/funding-rates"),
            ("GET", "/api/derivatives/open-interest/{symbol}"),
            ("GET", "/api/liquidations/levels/{symbol}"),
            ("GET", "/api/liquidations/map/{symbol}"),
            ("GET", "/api/liquidations/lines/{symbol}"),
            ("GET", "/api/liquidations/profile/{symbol}"),
            ("GET", "/api/onchain/whales"),
        ],
    ),
    (
        "Ownership",
        "Who holds what, and how those positions moved.",
        [
            ("GET", "/api/ownership/board"),
            ("GET", "/api/ownership/consensus"),
            ("GET", "/api/ownership/assets/{symbol}"),
            ("GET", "/api/ownership/moves"),
            ("GET", "/api/ownership/flow-note"),
        ],
    ),
    (
        "Borsa İstanbul (BIST)",
        "The Turkish market: equities, TEFAS funds, KAP filings and the macro "
        "series they are measured against.\n\n"
        "Two things about this surface differ from the rest of the API and will "
        "produce wrong answers if assumed away. **Every return is quoted twice.** "
        "A lira figure over a year in which consumer prices rose ~32% is not a "
        "result, so `returns`/`framed_returns` carry `nominal`, `real` "
        "(inflation-adjusted) and `usd` side by side; a null `real` means the "
        "window could not be deflated, never that inflation was zero. "
        "**Prices are delayed at least 15 minutes** — `delay_minutes` says so on "
        "every board that carries a quote.\n\n"
        "Symbols carry the venue: `BIST:THYAO`. A bare ticker never resolves to "
        "Borsa İstanbul unless the caller asks for it explicitly.",
        [
            ("GET", "/api/bist/overview"),
            ("GET", "/api/bist/market-note"),
            ("GET", "/api/bist/stocks"),
            ("GET", "/api/bist/stocks/{ticker}"),
            ("GET", "/api/bist/heatmap"),
            ("GET", "/api/bist/funds"),
            ("GET", "/api/bist/funds/{code}"),
            ("GET", "/api/bist/funds/{code}/holdings"),
            ("GET", "/api/bist/funds/compare"),
            ("GET", "/api/bist/funds/market-note"),
            ("GET", "/api/bist/macro"),
            ("GET", "/api/bist/kap"),
            ("GET", "/api/bist/kap/{index}/note"),
            ("GET", "/api/bist/restrictions"),
            ("GET", "/api/bist/calendar"),
            ("GET", "/api/bist/viop"),
            ("GET", "/api/bist/viop-note"),
            ("GET", "/api/bist/viop-map/underlyings"),
            ("GET", "/api/bist/viop-map/{ticker}"),
            ("GET", "/api/bist/positioning"),
            ("GET", "/api/bist/positioning-note"),
        ],
    ),
    (
        "Live feeds",
        "Events and the trade tape.",
        [
            ("GET", "/api/live/events"),
            ("GET", "/api/live/tape"),
        ],
    ),
    (
        "Chat (authenticated)",
        "The Oracle itself — the terminal's own reasoning layer over all of the above.",
        [
            ("GET", "/api/chat/status"),
            ("POST", "/api/chat"),
            ("POST", "/api/chat/jobs"),
            ("GET", "/api/chat/jobs/{job_id}"),
        ],
    ),
    (
        "Prediction markets",
        "What people are betting happens next, and a sourced read on why.\n\n"
        "The analysis endpoint may answer with a refusal instead of a verdict. "
        "That is a successful run, not an error: the pipeline declines when the "
        "evidence it could gather does not support a judgement, and the payload "
        "names every search it ran and every one that came back empty. A refusal "
        "still carries the market's odds, movement and holder concentration, all "
        "of which are measured rather than modelled.\n\n"
        "Why a market was opened is a separate job with its own endpoints. It is "
        "the one surface here allowed to answer without a source: when no dated "
        "reporting explains an opening, it returns `status: conjectured` and a "
        "`conjecture` naming the kind of event that usually opens a market like "
        "this one. Treat that field as a hypothesis, never as a finding — it "
        "carries no source id and is never used to write a verdict.",
        [
            ("GET", "/api/polymarket/board"),
            ("GET", "/api/polymarket/markets/{slug}"),
            ("GET", "/api/polymarket/map"),
            ("POST", "/api/polymarket/markets/{slug}/analysis/jobs"),
            ("GET", "/api/polymarket/analysis/jobs/{job_id}"),
            ("POST", "/api/polymarket/markets/{slug}/origin/jobs"),
            ("GET", "/api/polymarket/origin/jobs/{job_id}"),
        ],
    ),
    (
        "Watchlist (authenticated)",
        "The caller's own tracked symbols.",
        [
            ("GET", "/api/home/watchlist"),
            ("POST", "/api/home/watchlist"),
        ],
    ),
    (
        "Health",
        "Whether the instance and its upstreams are actually up.",
        [
            ("GET", "/api/system/health"),
            ("GET", "/api/system/readiness"),
        ],
    ),
]

HEADER = """<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: python scripts/build_agent_skill.py
     Source of truth: the FastAPI route definitions in backend/routers/. -->

# Oracle-X endpoint reference

Every path below is relative to the instance base URL (`$ORACLE_X_URL`,
default `http://localhost:8000`). Endpoints marked **auth** require
`Authorization: Bearer <supabase-jwt>`; see `auth.md`. Everything else is open
on a default instance.

Request and response bodies are described by their field names and types. When
a response shape is not declared on the route, the entry says so — call it once
and read the actual JSON rather than guessing.

"""


def resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    """Follow a local `#/components/schemas/X` pointer."""
    node: Any = spec
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    return node


def type_of(schema: dict[str, Any], spec: dict[str, Any]) -> str:
    """Render a schema as a short type name an agent can act on."""
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if "anyOf" in schema:
        parts = [type_of(s, spec) for s in schema["anyOf"] if s.get("type") != "null"]
        rendered = " | ".join(dict.fromkeys(parts))
        return f"{rendered}?" if len(parts) < len(schema["anyOf"]) else rendered
    if schema.get("type") == "array":
        return f"{type_of(schema.get('items', {}), spec)}[]"
    if "enum" in schema:
        return " | ".join(repr(v) for v in schema["enum"])
    return str(schema.get("type", "any"))


def render_params(operation: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for param in operation.get("parameters", []):
        schema = param.get("schema", {})
        flag = "required" if param.get("required") else "optional"
        default = schema.get("default")
        suffix = f", default `{default!r}`" if default is not None else ""
        note = param.get("description") or schema.get("description") or ""
        note = f" — {note.strip().splitlines()[0]}" if note else ""
        lines.append(
            f"- `{param['name']}` ({param['in']}, {type_of(schema, spec)}, {flag}{suffix}){note}"
        )
    return lines


def render_body(operation: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    body = operation.get("requestBody")
    if not body:
        return []
    content = body.get("content", {}).get("application/json")
    if not content:
        return []
    schema = content.get("schema", {})
    if "$ref" in schema:
        schema = resolve_ref(spec, schema["$ref"])
    props = schema.get("properties")
    if not props:
        return ["- body: free-form JSON"]
    required = set(schema.get("required", []))
    lines = ["", "Body (JSON):"]
    for name, prop in props.items():
        flag = "required" if name in required else "optional"
        note = prop.get("description") or ""
        note = f" — {note.strip().splitlines()[0]}" if note else ""
        lines.append(f"- `{name}` ({type_of(prop, spec)}, {flag}){note}")
    return lines


def render_response(operation: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    ok = operation.get("responses", {}).get("200", {})
    content = ok.get("content", {}).get("application/json", {})
    schema = content.get("schema", {})
    if "$ref" in schema:
        resolved = resolve_ref(spec, schema["$ref"])
        props = resolved.get("properties", {})
        if props:
            fields = ", ".join(f"`{n}`" for n in list(props)[:12])
            more = ", …" if len(props) > 12 else ""
            return [
                "",
                f"Returns `{schema['$ref'].rsplit('/', 1)[-1]}`: {fields}{more}",
            ]
    if schema and schema != {}:
        return ["", f"Returns `{type_of(schema, spec)}`."]
    return ["", "Response shape is not declared on the route — inspect one call."]


def render(spec: dict[str, Any]) -> str:
    out: list[str] = [HEADER.rstrip(), ""]
    missing: list[str] = []

    for title, blurb, endpoints in ENDPOINT_GROUPS:
        out += [f"## {title}", "", blurb, ""]
        for method, path in endpoints:
            operation = spec.get("paths", {}).get(path, {}).get(method.lower())
            if operation is None:
                missing.append(f"{method} {path}")
                continue
            auth = " · **auth**" if operation.get("security") else ""
            summary = operation.get("summary", "").strip()
            out.append(f"### `{method} {path}`{auth}")
            out.append("")
            if summary:
                out.append(summary)
                out.append("")
            doc = (operation.get("description") or "").strip()
            if doc:
                out += [doc, ""]
            params = render_params(operation, spec)
            if params:
                out += ["Parameters:", *params]
            out += render_body(operation, spec)
            out += render_response(operation, spec)
            out.append("")

    if missing:
        raise SystemExit(
            "These allowlisted endpoints no longer exist in the API:\n  "
            + "\n  ".join(missing)
            + "\nUpdate ENDPOINT_GROUPS in scripts/build_agent_skill.py."
        )

    return "\n".join(out).rstrip() + "\n"


def build_zip() -> None:
    """Package each skill directory for distribution."""
    for skill_dir, zip_path in ZIP_TARGETS:
        if not (skill_dir / "SKILL.md").exists():
            raise SystemExit(f"{skill_dir} has no SKILL.md")
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(skill_dir.rglob("*")):
                if not path.is_file():
                    continue
                # Tooling leaves caches inside the skill directory —
                # .ruff_cache, __pycache__, .DS_Store. They are gitignored, so
                # nothing catches them on the way into a zip that *is*
                # committed, and they ship to everyone who installs the skill.
                if any(
                    part.startswith(".") or part == "__pycache__" for part in path.parts
                ):
                    continue
                archive.write(path, path.relative_to(skill_dir.parent))
        print(f"wrote {zip_path.relative_to(REPO_ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the committed reference is stale",
    )
    parser.add_argument("--zip", action="store_true", help="also rebuild the .zip")
    args = parser.parse_args()

    rendered = render(load_spec())

    if args.check:
        current = REFERENCE.read_text() if REFERENCE.exists() else ""
        if current != rendered:
            diff = difflib.unified_diff(
                current.splitlines(keepends=True),
                rendered.splitlines(keepends=True),
                fromfile="committed",
                tofile="generated",
            )
            sys.stdout.writelines(diff)
            print(
                "\nagent-skill endpoint reference is stale. "
                "Run: python scripts/build_agent_skill.py",
                file=sys.stderr,
            )
            return 1
        print("agent-skill endpoint reference is up to date")
        return 0

    REFERENCE.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE.write_text(rendered)
    print(f"wrote {REFERENCE.relative_to(REPO_ROOT)}")
    if args.zip:
        build_zip()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
