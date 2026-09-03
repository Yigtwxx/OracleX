# Oracle-X Agent Skills

Three [AgentSkills](https://agentskills.io/specification). They answer
different questions and are installed independently — take the one that matches
the work, not all three:

| Skill | For |
|---|---|
| **`oracle-x-api`** | Reading a running instance — crypto and US equities, technicals, news analysis, macro regime, chain metrics, liquidations, prediction markets, ownership, and the vector memory. |
| **`oracle-x-bist`** | Borsa İstanbul — BIST equities, TEFAS funds, KAP, VİOP margins and positioning, and the Turkish macro series. Half of it needs no instance at all. |
| **`oracle-x-dev`** | Working on the codebase — adding an endpoint, an upstream, a chain adapter, a prompt, and testing any of it the way this repository does. |

**Why the market split.** BIST is 32 endpoints, roughly a third of the
allowlist, and most installs are not in Turkey. Shipping them together means an
agent in Frankfurt carries TEFAS and VİOP in context on every question about
BTC and gets nothing back for it. Split, the cost lands on the people who asked
for it. `oracle-x-bist` also turned out to be the one that stands on its own:
how a lira return becomes a real one, and where Takasbank actually publishes
the scan range, are facts about the market rather than about any server, so it
is worth installing before there is an instance to point it at.

The specification is shared, so the same directories work in
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

## Install `mcp-server/` first

[`mcp-server/`](../mcp-server/) exposes the same instance as 36 MCP tools, and
it is what to reach for if the goal is a model that can see the terminal's
numbers. A tool list is already in the model's context, so the only decision
left is which tool to call. A skill has to be *looked up* before it can be
used, and the measurement below is what happens when nothing prompts the
lookup.

These skills earn their place next to it, not instead of it. `oracle-x-api` is
for an agent writing code against the API — it reaches for documentation on its
own there, and the endpoint reference is generated from the running app.
`oracle-x-dev` is for an agent editing this repository. Installing the server
and the skills together is the normal case.

## Before you install: it will not trigger on its own

This was measured, not assumed. Twenty realistic queries — "what is BTC doing",
"where are ETH's levels", "why did SOL move today" — run against three
rewrites of the skill's description. The agent chose to consult the skill on
almost none of them. Whenever it did, it used it correctly; it simply did not
go looking. Rewording moved nothing, and the original description scored best
of the three.

The cause is structural rather than editorial. A skill has to be *looked up*,
and a model asked what BTC is doing already believes it can answer. No wording
gets in front of that, because the decision to go looking comes first.

That leaves two ways to install it honestly:

* **Ask for it by name.** "Use the Oracle-X skill and tell me where BTC's
  levels are" works exactly as designed — the endpoints, the auth rules and the
  refusal to invent a number are all there once the skill is open.
* **Writing code against the API.** Here the agent is already reading
  documentation, so it opens the skill on its own, and
  `references/endpoints.md` is generated from the running app rather than
  remembered.

Which is the whole reason `mcp-server/` is named first above. Nothing in the
wording of a skill reaches a model that never went looking.

## Install

```bash
# Claude Code — the marketplace carries the MCP server alongside the skills
claude plugin marketplace add Yigtwxx/OracleX
claude plugin install oracle-x@oracle-x         # MCP tools + this skill + commands
claude plugin install oracle-x-bist@oracle-x
claude plugin install oracle-x-dev@oracle-x

# skills.sh — reads them straight out of this repository
npx skills add Yigtwxx/OracleX --skill oracle-x-api     # crypto, US equities, macro
npx skills add Yigtwxx/OracleX --skill oracle-x-bist    # Borsa İstanbul
npx skills add Yigtwxx/OracleX --skill oracle-x-dev     # working on the code

# ClawHub — all three are published under @yigtwxx
clawhub install @yigtwxx/oracle-x-api
clawhub install @yigtwxx/oracle-x-bist
clawhub install @yigtwxx/oracle-x-dev
```

The [skills.sh](https://github.com/vercel-labs/skills) CLI reads the skill
straight out of this repository — there is nothing to publish and no registry
entry — and installs it into whichever agents it finds on the machine. The
`--skill` flag matches the `name:` in the frontmatter, not the directory.

Or take them by hand: download
[`Oracle-X-Skill.zip`](./Oracle-X-Skill.zip),
[`Oracle-X-BIST-Skill.zip`](./Oracle-X-BIST-Skill.zip) or
[`Oracle-X-Dev-Skill.zip`](./Oracle-X-Dev-Skill.zip) and unpack into your
agent's skills directory, or copy a directory out of a clone:

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
├── README.md                   # the ClawHub-facing page; not read by an agent
├── references/
│   ├── endpoints.md            # generated — every allowlisted endpoint, in full
│   ├── auth.md                 # tokens: obtaining, using, verifying
│   └── recipes.md              # the multi-step reads worth knowing
└── examples/                   # runnable httpx clients

oracle-x-bist/
├── SKILL.md                    # the rules that hold with no server, then the table
├── README.md                   # the ClawHub-facing page; not read by an agent
└── references/
    ├── endpoints.md            # generated — every BIST endpoint, in full
    └── viop-margins.md         # reading Takasbank's SPAN file directly

oracle-x-dev/
├── SKILL.md                    # the four gates, and the rules that bite
├── README.md                   # the ClawHub-facing page; not read by an agent
└── references/
    ├── endpoint.md             # router → service → cache → error, and registration
    ├── upstream.md             # http_client, and mapping a host onto the health badge
    ├── chains.md               # the duck-typed chain adapter contract
    ├── llm.md                  # the provider chain, prompts as files, the note pattern
    └── testing.md              # monkeypatch at the import site, and why lib/ is where tests live
```

`oracle-x-dev` deliberately does not repeat the repository's `CLAUDE.md`. That
file records what the system *is*; the skill records how to extend it.

In both, `SKILL.md` is loaded whenever the skill triggers, so it holds only what
an agent needs to choose correctly. The `references/` files are read on demand —
the endpoint reference alone is 800 lines and has no business in context until a
call actually needs it.

## Keeping it current

`references/endpoints.md` is generated from the backend's own OpenAPI schema, so
it cannot drift from the deployed API without CI noticing:

```bash
python scripts/build_agent_skill.py           # regenerate
python scripts/build_agent_skill.py --check   # CI: fail if stale
python scripts/build_agent_skill.py --zip     # rebuild both distributables
```

Only `oracle-x-api` has a generated part. `oracle-x-dev` is entirely
hand-written, because conventions are not derivable from a schema.

The generator imports the app rather than calling a running server, so it works
in a checkout with no instance up. It covers an allowlist of ~50 endpoints
defined in the script: the terminal exposes about 120 operations, but the rest
are the UI talking to itself and would cost the agent context without buying it
a capability. Adding an endpoint to the skill means adding one line to
`ENDPOINT_GROUPS` and, if it deserves one, a row in the SKILL.md table.

`SKILL.md` itself stays hand-written. Which endpoint answers which question is
a judgement, and generating it would produce a list rather than guidance.

## Publishing to ClawHub

Both skills are published under `@yigtwxx` and moderated CLEAN. The version
there is not the repository's — a republish auto-increments the patch, so the
number moves on its own; `clawhub inspect oracle-x-api` is the honest source.
ClawHub relicenses what it hosts as MIT-0, so the copy there carries no
attribution requirement even though this repository is MIT.

The `README.md` inside each skill exists for this channel. Someone installing
from ClawHub never sees the file you are reading, and for `oracle-x-api` the
trigger caveat above is the first thing they need. Neither file is loaded by an
agent — only `SKILL.md` is — so they cost context nothing.

ClawHub does not index GitHub on its own — a skill gets there by being pushed,
from the account that owns the repository. To publish an update:

```bash
npm install -g clawhub
clawhub login                                   # GitHub OAuth

clawhub skill publish ./agent-skill/oracle-x-api \
  --slug oracle-x-api \
  --name "Oracle-X API" \
  --categories finance \
  --topics "crypto,stocks,market-data,technical-analysis,prediction-markets" \
  --dry-run

clawhub skill publish ./agent-skill/oracle-x-bist \
  --slug oracle-x-bist \
  --name "Oracle-X BIST" \
  --categories finance \
  --topics "borsa-istanbul,viop,bist,tefas,turkish-stocks" \
  --dry-run

clawhub skill publish ./agent-skill/oracle-x-dev \
  --slug oracle-x-dev \
  --name "Oracle-X Development" \
  --categories development \
  --topics "fastapi,nextjs,codebase-conventions,financial-terminal,oracle-x" \
  --dry-run
```

Drop `--dry-run` once the output looks right; a republish auto-increments the
patch version.

**Five topics is the hard limit**, and `--dry-run` does not enforce it — it
reports `Would publish` and the real call then fails with `Topics are limited
to 5`. So the five are a budget, and they were spent on measurement rather than
on what the skill is mostly about.

ClawHub's search matches the `description` from `SKILL.md` plus the topics, and
returns ten results per query. Searched against it, `crypto`, `stocks`,
`market-data`, `technical-analysis`, `trading`, `liquidation`, `funding-rates`,
`macro`, `whale`, `polymarket`, `rag` and `self-hosted` each return a full page
of competitors and none of them surface these skills — including the terms the
old topic list already spent slots on. `bist` returns two results; `viop`,
`borsa-istanbul`, `tefas`, `turkish-stocks` and `xu100` return zero. An
uncontested query where the skill can be the only answer is worth more than a
better ranking in a contested one it will not win, and the BIST surface is 28
endpoints no other skill on the registry exposes.

So the Turkish terms all went to `oracle-x-bist`, where they describe what the
skill actually serves, and `oracle-x-api` keeps the broad ones. Measured after
publishing: `viop`, `borsa-istanbul`, `tefas` and `borsa istanbul` each return
this skill as the only result, `bist` ranks it second of three, `turkish`
fourth of five. `crypto` still does not surface it at all, which is the
expected outcome and the reason the slots were spent the way they were.

The split between the two fields is deliberate. Topics carry the ASCII
spellings (`viop`, `borsa-istanbul`) because that is what a search box
receives; the `description` carries the human ones (VİOP, Borsa İstanbul)
because that is what an agent reads.

Two more things ClawHub checks that are
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

The Claude Code plugin packaging looked like exactly that risk and is not: its
marketplace entries name `./agent-skill/<skill>` explicitly, so nothing had to
move and no second copy exists. See [`../plugins/README.md`](../plugins/README.md).
