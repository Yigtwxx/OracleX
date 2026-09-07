# Claude Code plugin packaging

The three AgentSkills under [`agent-skill/`](../agent-skill/) and the
[`mcp-server/`](../mcp-server/) already work on their own. This directory is
what turns them into three installable Claude Code plugins, declared in
[`../.claude-plugin/marketplace.json`](../.claude-plugin/marketplace.json).

```bash
claude plugin marketplace add Yigtwxx/OracleX
claude plugin install oracle-x@oracle-x         # MCP tools + the API skill + commands
claude plugin install oracle-x-bist@oracle-x    # Borsa İstanbul
claude plugin install oracle-x-dev@oracle-x     # working on this codebase
```

The slash commands and the hook scripts live here. The skills are not copied —
the marketplace entries point at `agent-skill/` directly, so there is one copy
of each skill in the repository and no chance of the plugin shipping a stale
one. The subagents are the exception: they sit in [`../agents/`](../agents/) at
the repository root, because that is the only place the loader looks. See the
fifth item below.

## Six things that cost an afternoon to discover

The plugin format has some sharp edges, and none of them fail loudly. All six
were found with `claude plugin validate` passing and the component still
refusing to load. `claude plugin details <name>@oracle-x` prints a component
inventory, and a `(0)` there is the only reliable symptom.

**Component specs must live in exactly one place.** A `plugin.json` that
declares `commands` while the marketplace entry declares `skills` fails with
*"conflicting manifests"* — even though neither declares the same component
type. Since `plugin.json` has no `skills` field at all and these skills live
outside `skills/`, the marketplace entry has to be the single source, and there
is no `.claude-plugin/plugin.json` in this repository at all.

**`skills` paths resolve against the entry's `source`, not the marketplace
root.** Giving `oracle-x-bist` a tidy `source: "./plugins/oracle-x-bist"`
made it look for `plugins/oracle-x-bist/agent-skill/oracle-x-bist`. All three
entries are therefore rooted at `./`, and what separates them is which skills
and commands each one lists.

**`mcpServers` has to be inline.** As a path — `"./plugins/oracle-x/.mcp.json"`,
which is what the manifest reference documents for `plugin.json` — the
marketplace entry validates, installs, enables, and reports `MCP servers (0)`.
The server object is written into the entry itself instead.

**`agents` is not read from the marketplace entry at all.** A string is
rejected by validation; an array of directories is rejected; an array of `.md`
file paths validates cleanly and loads nothing — `Agents (0)`. The only
mechanism that works is auto-discovery of `<source>/agents/*.md`, and since all
three entries are rooted at `./` for the reason above, that directory is the
repository root's `agents/` and all three plugins carry all three subagents.
That is not the partition the skills get, and it costs about 640 always-on
tokens in a session that installed only one plugin. It is the trade the format
allows: each agent's description states its precondition, and each one stops in
a sentence when that precondition is absent — no instance answering, or not
this repository.

**`hooks` behaves like `mcpServers`, not like `commands`.** As a path to a
`hooks.json` it validates, installs, and reports `Hooks (0)`. The hook events
are written into the marketplace entry inline. Only the shell scripts live
under `plugins/<name>/hooks/`, referenced as
`${CLAUDE_PLUGIN_ROOT}/plugins/<name>/hooks/<script>.sh` — `CLAUDE_PLUGIN_ROOT`
is the repository root here, again because `source` is `./`.

**`claude plugin validate` does not check that paths exist.** A `skills` entry
pointing at a directory that was never created passes validation. The only real
test is `claude plugin marketplace add`, then `claude plugin list`, then
`claude plugin details <name>@oracle-x` for the component inventory.

## What the hooks do

`oracle-x` has one: a `SessionStart` probe that spends at most two seconds
asking `/api/system/health` whether an instance is answering. Without it, a
dead backend shows up as all 36 MCP tools failing several turns into a
conversation, which reads as a broken plugin rather than a stopped server. It
prints one line, reports the badge word and any category that is actually
down — `idle` there means nobody has called that upstream yet, not that it is
broken — and always exits 0. It is context, never a gate.

`oracle-x-dev` has two, and both are inert outside this repository: the guard
checks for `backend/services/health_registry.py` before it decides anything,
and a name check would have matched any checkout that happened to be called
oracle-x.

`guard-bash.sh` runs on `PreToolUse` for `Bash` and enforces four traps that
`CLAUDE.md` already describes in prose. Prose does not stop a command that
looks correct, and all four fail quietly:

| Command | Decision | Why |
|---|---|---|
| `git add -A`, `git add .` | deny | `backend/data/` is rewritten on every run, and hand-maintained seed files sit among the generated ones |
| `ruff` without `backend` in the line | deny | it reads `backend/pyproject.toml` (`line-length = 100`); from the root it silently uses its own defaults and CI then disagrees with the local run |
| `pytest` without `backend` or `mcp-server` | ask | the backend sets `pythonpath = ["."]` and imports as `from services... import`, which only resolves from `backend/` |
| `npm run build` while `:3100` is listening | ask | the build and `next dev` share `frontend/.next/` |

The `Stop` hook is prompt-based and narrow on purpose: it approves unless
backend or frontend source changed, no gate was run afterwards, and it has not
already blocked once. A completion gate that fires twice is a gate people
disable.

Hooks load at session start. Editing them means restarting Claude Code, and
`claude --debug` is what shows whether they registered.

## The subagents

Three, in [`../agents/`](../agents/), all dispatched rather than invoked:

- **`market-analyst`** — a question that needs six or seven MCP calls, answered
  in a paragraph. The point is that the payloads stay in the subagent.
- **`bist-analyst`** — the same for Borsa İstanbul, where the discipline that
  matters is quoting the frame in the same sentence as the number. Works
  through the MCP tools when `oracle-x` is installed and through `curl` when it
  is not.
- **`oracle-x-reviewer`** — read-only review of a diff against the conventions
  CI does not check: identity from `AuthUser`, thin routers, upstreams through
  the shared helper and the health registry, models only through
  `services/llm`, prompt names as string literals, unmeasured as `None`.

## Why the MCP server is on one plugin only

`oracle-x` carries the MCP server; the other two do not. There is one server
and it answers for the whole terminal — six of its 36 tools are Turkish — so
declaring it on a second plugin would start a second copy of the same process
under the same name whenever both are installed. `oracle-x-bist` therefore says
in its description that `oracle-x` is what brings its MCP surface, and its
slash commands call the HTTP API directly so that the plugin is still useful
installed alone.

`uvx --from ${CLAUDE_PLUGIN_ROOT}/mcp-server oracle-x-mcp` builds the package
on first run, so nobody has to create a virtualenv by hand. No `env` block is
declared: the client already defaults to `http://localhost:8000`, and an
unexpanded `"${ORACLE_X_URL}"` would be passed through as a literal base URL
that fails on every call. Export the variable in the shell to point at a remote
instance.
