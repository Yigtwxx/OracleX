---
description: Whether the Oracle-X instance and its upstreams are actually up
allowed-tools: mcp__oracle-x__check_instance, Bash
---

Report the instance's health.

Call `check_instance`. If the MCP server itself cannot reach the terminal, fall
back to:

```bash
curl -sf "${ORACLE_X_URL:-http://localhost:8000}/api/system/health" | head -c 800
```

The health endpoint is passive — it reports what the last real call to each
upstream did and issues no requests of its own — so reading it costs the
instance nothing and can be repeated freely.

Answer with: is it up, which categories are degraded, and what a user would
lose because of each. Categories are grouped by what a person loses rather than
by hostname, so "degraded" there is already the user-facing statement.

If the connection is refused, say the terminal is not running and give the
command to start it: `./start.sh` from the repository root.
