"""The app's OpenAPI document, built in-process.

Two generators need this — `build_agent_skill.py` for the endpoint reference and
`build_repo_facts.py` for the marketing surface — and the whole point of both is
that a document cannot drift from the app it describes. Two copies of the loader
would mean that the day `create_app` moves, one of the two gates keeps passing
against a stale import path while the other fails, and the failure gets read as
the generator being broken rather than the docs being wrong.

The leading underscore marks this as a helper rather than an entry point. It
imports cleanly from a sibling because `python scripts/x.py` puts `scripts/` at
`sys.path[0]`, so no package machinery is needed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND = REPO_ROOT / "backend"


def load_spec() -> dict[str, Any]:
    """Build the app in-process and return its OpenAPI document.

    No server, no HTTP, no network: the schema is a property of the route
    definitions, and starting uvicorn to read it would make a docs check depend
    on a port being free.
    """
    sys.path.insert(0, str(BACKEND))
    from dependencies.auth import get_optional_user
    from main import create_app

    app = create_app()
    spec = app.openapi()

    # FastAPI emits `security` for an optional auth dependency exactly as it
    # does for a required one, so a public route that merely *honours* a
    # signed-in reader — every AI-note endpoint does, to pick up that reader's
    # own provider — would be published to outside agents as needing a token,
    # and an agent without one would skip a third of the BIST surface. Mark
    # those so a writer can tell "must sign in" from "may sign in".
    for route in _routes(app):
        dependant = getattr(route, "dependant", None)
        if dependant is None or not _uses(dependant, get_optional_user):
            continue
        operations = spec.get("paths", {}).get(getattr(route, "path_format", route.path), {})
        for method in getattr(route, "methods", None) or []:
            operation = operations.get(method.lower())
            if operation is not None:
                operation["x-auth-optional"] = True

    return spec


def _routes(owner: Any) -> Iterator[Any]:
    """
    Every endpoint under `owner`, flattened.

    `app.routes` does not hold the endpoints directly: `include_router` leaves a
    wrapper behind that keeps a reference to the router it included, so a plain
    loop over `app.routes` sees a handful of wrappers and none of the hundreds of
    routes inside them — and silently marks nothing.
    """
    for entry in getattr(owner, "routes", []):
        if hasattr(entry, "dependant"):
            yield entry
        inner = getattr(entry, "original_router", None)
        if inner is not None:
            yield from _routes(inner)


def _uses(dependant: Any, call: Any) -> bool:
    """Whether `call` appears anywhere in this route's dependency tree."""
    if dependant.call is call:
        return True
    return any(_uses(child, call) for child in dependant.dependencies)
