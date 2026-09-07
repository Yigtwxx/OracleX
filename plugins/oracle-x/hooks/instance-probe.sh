#!/usr/bin/env bash
# SessionStart probe for the Oracle-X plugin.
#
# The 36 MCP tools all talk HTTP to one instance. When nothing is listening,
# every one of them fails the same way several turns into a conversation, which
# reads as a broken plugin rather than a stopped backend. One cheap line at
# session start turns that into a known fact before the first tool call.
#
# Always exits 0. This is context, never a gate.
set -uo pipefail

BASE="${ORACLE_X_URL:-http://localhost:8000}"

if ! command -v curl >/dev/null 2>&1; then
  exit 0
fi

# --max-time bounds the whole session-start path; a hung probe would delay the
# first prompt, which is worse than not knowing.
body=$(curl -sf --max-time 2 "${BASE}/api/system/health" 2>/dev/null) || {
  echo "Oracle-X: no instance answering at ${BASE}. The oracle-x MCP tools will fail until one is running (./start.sh), or set ORACLE_X_URL to a remote instance."
  exit 0
}

# Report only the shape of the answer. The health payload names providers and
# is not something to paste into a transcript wholesale.
if command -v python3 >/dev/null 2>&1; then
  echo "$body" | python3 -c '
import json, sys

try:
    data = json.load(sys.stdin)
except Exception:
    print("Oracle-X: instance is answering, health payload unrecognised.")
    raise SystemExit(0)

# `status` collapses the board to one word: live, degraded, offline or
# starting. `categories` is a list of rows, each with its own `state` -- and
# `idle` there means nobody has called that upstream yet, not that it is broken.
status = data.get("status", "unknown")
rows = data.get("categories") or []
bad = sorted(
    r.get("key", "?") for r in rows
    if isinstance(r, dict) and r.get("state") in ("down", "degraded")
)
if bad:
    print(f"Oracle-X: instance up, badge reads {status}; not answering: " + ", ".join(bad) + ".")
else:
    print(f"Oracle-X: instance up, badge reads {status}.")
'
else
  echo "Oracle-X: instance up at ${BASE}."
fi

exit 0
