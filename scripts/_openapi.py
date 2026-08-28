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

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND = REPO_ROOT / "backend"


def load_spec() -> dict[str, Any]:
    """Build the app in-process and return its OpenAPI document.

    No server, no HTTP, no network: the schema is a property of the route
    definitions, and starting uvicorn to read it would make a docs check depend
    on a port being free.
    """
    sys.path.insert(0, str(BACKEND))
    from main import create_app

    return create_app().openapi()
