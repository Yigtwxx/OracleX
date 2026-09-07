#!/usr/bin/env bash
# PreToolUse guard for Bash, for work inside the Oracle-X repository.
#
# Four traps that CLAUDE.md documents in prose. Prose does not stop a command
# that is already correct-looking, and all four of these fail quietly:
#
#   git add -A      stages the generated files under backend/data/
#   ruff from root   misses backend/pyproject.toml's line-length = 100
#   pytest from root the backend imports as `from services...` (pythonpath = ["."])
#   next build       shares .next/ with a running dev server and clobbers it
#
# Only acts inside this repository. The oracle-x-dev plugin is installed
# globally, and these rules are noise anywhere else.
set -uo pipefail

input=$(cat)

if ! command -v jq >/dev/null 2>&1; then
  exit 0
fi

project_dir=$(printf '%s' "$input" | jq -r '.cwd // empty')
[ -n "$project_dir" ] || project_dir="${CLAUDE_PROJECT_DIR:-$PWD}"

# The marker is a file that exists only here. A name check would match any
# checkout that happened to be called oracle-x.
if [ ! -f "$project_dir/backend/services/health_registry.py" ]; then
  exit 0
fi

command_text=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')
[ -n "$command_text" ] || exit 0

decide() {
  # $1 = allow|deny|ask, $2 = reason
  jq -cn --arg d "$1" --arg r "$2" \
    '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: $d, permissionDecisionReason: $r}}'
  exit 0
}

# --- git add -A -------------------------------------------------------------
# backend/data/ is rewritten on every run and gitignored, but a handful of seed
# files sit next to the generated ones. -A after running the backend stages
# whatever the run left behind.
if printf '%s' "$command_text" | grep -Eq 'git[[:space:]]+add[[:space:]]+(-A\b|--all\b|\.[[:space:]]*$|\.[[:space:]]+)'; then
  decide deny "git add -A stages whatever the last backend run wrote under backend/data/. Add the files you changed by name, or run git status first and read it."
fi

# --- ruff from the repo root ------------------------------------------------
# ruff run from here picks up its own defaults instead of backend/pyproject.toml,
# so it reformats to 88 columns and CI disagrees with the local run.
if printf '%s' "$command_text" | grep -Eq '(^|[;&|[:space:]])ruff([[:space:]]|$)' \
   && ! printf '%s' "$command_text" | grep -q 'backend'; then
  decide deny "ruff reads backend/pyproject.toml (line-length = 100). From the repo root it silently uses its own defaults. Run: cd backend && ruff check . && ruff format --check ."
fi

# --- pytest from the wrong directory ----------------------------------------
# The backend sets pythonpath = ["."] and imports as `from services... import`,
# which only resolves from backend/. mcp-server has its own suite.
if printf '%s' "$command_text" | grep -Eq 'pytest' \
   && ! printf '%s' "$command_text" | grep -Eq 'backend|mcp-server'; then
  decide ask "The backend suite only imports from backend/ (pythonpath = [\".\"]). If this is the backend, run it as: cd backend && source venv/bin/activate && python -m pytest."
fi

# --- next build against a live dev server -----------------------------------
# `npm run build` and `next dev` share frontend/.next/. Building while the dev
# server holds it leaves both in a state neither recovers from cleanly.
if printf '%s' "$command_text" | grep -Eq 'next[[:space:]]+build|npm[[:space:]]+run[[:space:]]+build' \
   && command -v lsof >/dev/null 2>&1 \
   && lsof -ti tcp:3100 >/dev/null 2>&1; then
  decide ask "Something is serving on :3100. A production build shares frontend/.next/ with the dev server and will clobber it. Stop the dev server first, or build against a copied tree."
fi

exit 0
