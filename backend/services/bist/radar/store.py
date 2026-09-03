"""
The last finished scan, on disk, one file per horizon.

A scan costs a minute and a few hundred upstream requests, and the tab is
opened far more often than it is re-run. Persisting the result means the page
opens onto the last read — stamped with when it was taken — rather than onto an
empty pane and a button.
"""

import os
from typing import Any, Optional

from services.asset_registry import DATA_DIR, read_json_cache, write_json_cache


def _path(horizon: str) -> str:
    return os.path.join(DATA_DIR, f"bist_radar_last_{horizon}.json")


def read_last(horizon: str) -> Optional[dict[str, Any]]:
    payload = read_json_cache(_path(horizon))
    return payload if isinstance(payload, dict) else None


def write_last(horizon: str, result: dict[str, Any]) -> None:
    write_json_cache(_path(horizon), result)
