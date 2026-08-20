# Oracle-X Agent Skill

An [AgentSkill](https://agentskills.io/specification) that teaches a coding
agent to read a running Oracle-X instance — prices and technicals for crypto
and equities, news with its LLM analysis, macro regime, chain metrics,
liquidations, ownership, and the terminal's vector memory of past market
events.

The specification is shared, so the same directory works in
[Claude Code](https://claude.com/product/claude-code),
[OpenClaw](https://github.com/openclaw/openclaw) and other agentic tools.

## What it is for

Oracle-X already answers these questions in its own UI. The skill exists so
that an agent working somewhere else — in an editor, in a terminal, inside
another workflow — can ask the same questions without a bespoke integration.
"What are BTC's levels and has this setup resolved before" becomes two HTTP
calls the agent knows how to make, against data the operator already trusts.

It needs a reachable instance. This is the read side of a server, not a data
source of its own.

## Install

```bash
npx skills add Yigtwxx/OracleX --skill oracle-x-api
```

The [skills.sh](https://github.com/vercel-labs/skills) CLI reads the skill
straight out of this repository — there is nothing to publish and no registry
entry — and installs it into whichever agents it finds on the machine. The
`--skill` flag matches the `name:` in the frontmatter, not the directory.

Or take it by hand: download
[`Oracle-X-Skill.zip`](./Oracle-X-Skill.zip) and unpack it into your agent's
skills directory, or copy the directory out of a clone:

```bash
cp -r agent-skill/oracle-x-api ~/.claude/skills/
```

Then point it at your instance:

```bash
export ORACLE_X_URL=http://localhost:8000   # default; set for a remote instance
export ORACLE_X_TOKEN=...                   # only for chat and watchlist
```

Most of the surface is open on a default instance. The token is a Supabase
access token and is needed only for endpoints scoped to a person — see
[`oracle-x-api/references/auth.md`](./oracle-x-api/references/auth.md).

## What is inside

```
oracle-x-api/
├── SKILL.md                    # the decision table: which question → which endpoint
├── references/
│   ├── endpoints.md            # generated — every allowlisted endpoint, in full
│   ├── auth.md                 # tokens: obtaining, using, verifying
│   └── recipes.md              # the multi-step reads worth knowing
└── examples/                   # runnable httpx clients
```

`SKILL.md` is loaded whenever the skill triggers, so it holds only what an agent
needs to choose correctly. The `references/` files are read on demand — the full
endpoint reference is 800 lines and has no business in context until a call
actually needs it.

## Keeping it current

`references/endpoints.md` is generated from the backend's own OpenAPI schema, so
it cannot drift from the deployed API without CI noticing:

```bash
python scripts/build_agent_skill.py           # regenerate
python scripts/build_agent_skill.py --check   # CI: fail if stale
python scripts/build_agent_skill.py --zip     # rebuild the distributable
```

The generator imports the app rather than calling a running server, so it works
in a checkout with no instance up. It covers an allowlist of ~50 endpoints
defined in the script: the terminal exposes about 120 operations, but the rest
are the UI talking to itself and would cost the agent context without buying it
a capability. Adding an endpoint to the skill means adding one line to
`ENDPOINT_GROUPS` and, if it deserves one, a row in the SKILL.md table.

`SKILL.md` itself stays hand-written. Which endpoint answers which question is
a judgement, and generating it would produce a list rather than guidance.

## Publishing to ClawHub

ClawHub does not index GitHub on its own — a skill gets there by being pushed,
from the account that owns the repository:

```bash
npm install -g clawhub
clawhub login                                   # GitHub OAuth
clawhub skill publish ./agent-skill/oracle-x-api \
  --slug oracle-x-api \
  --name "Oracle-X API" \
  --categories finance \
  --topics "crypto,stocks,market-data,technical-analysis,rag" \
  --dry-run
```

Drop `--dry-run` once the output looks right. It installs as
`clawhub install @Yigtwxx/oracle-x-api`. Two things ClawHub checks that are
easy to get wrong: the `metadata.openclaw` block has to declare every
environment variable the skill actually reads, or its scanner flags the
mismatch — `ORACLE_X_URL` and `ORACLE_X_TOKEN` are declared for that reason —
and the bundle honours `.gitignore`, so a tool cache left in the directory
ships with it.

One structural caveat worth knowing before moving anything: skills.sh looks in
`skills/`, `.claude/skills/` and about sixty other conventional locations
first, and only falls back to a recursive search when none of them contain a
skill. `agent-skill/` is found by that fallback. If a `skills/` directory is
ever added to this repository for something else, discovery here stops working
and the skill has to move into it.
