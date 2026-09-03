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

Only the slash commands live here. The skills are not copied — the marketplace
entries point at `agent-skill/` directly, so there is one copy of each skill in
the repository and no chance of the plugin shipping a stale one.

## Four things that cost an afternoon to discover

The plugin format has some sharp edges, and none of them fail loudly. All four
were found with `claude plugin validate` passing and the plugin still refusing
to load.

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

**`claude plugin validate` does not check that paths exist.** A `skills` entry
pointing at a directory that was never created passes validation. The only real
test is `claude plugin marketplace add`, then `claude plugin list`, then
`claude plugin details <name>@oracle-x` for the component inventory.

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
