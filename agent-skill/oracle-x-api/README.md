# Oracle-X API — AgentSkill

Read live market intelligence from a running [Oracle-X](https://github.com/Yigtwxx/OracleX)
terminal: spot prices and candles for crypto and equities, computed
support/resistance zones, news with its LLM analysis, macro regime, per-chain
metrics, liquidations, funding, whale flow, institutional ownership, and a
vector memory of past market events.

This is the read side of a server you run, not a data source of its own. It
needs a reachable instance — by default `http://localhost:8000`.

## Before you install: it will not trigger on its own

This was measured, not assumed. Twenty realistic queries — "what is BTC doing",
"where are ETH's levels", "why did SOL move today" — were run against three
rewrites of this skill's description. The agent chose to consult the skill on
almost none of them. Whenever it did, it used it correctly; it simply did not
go looking. Rewording moved nothing, and the original description scored best
of the three.

The cause is structural rather than editorial. A skill has to be *looked up*,
and a model asked what BTC is doing already believes it can answer. No wording
gets in front of that, because the decision to go looking comes first.

That leaves two ways to install it honestly:

* **Ask for it by name.** "Use the Oracle-X skill and tell me where BTC's
  levels are" works exactly as designed — the endpoint map, the auth rules and
  the refusal to invent a number are all there once the skill is open.
* **Writing code against the API.** Here an agent reaches for documentation on
  its own, and `references/endpoints.md` is generated from the running app
  rather than remembered.

If what you want is the terminal's numbers reaching a model *without being
asked*, install the repository's [`mcp-server/`](https://github.com/Yigtwxx/OracleX/tree/main/mcp-server)
instead — the same data as 26 MCP tools. A tool list is already in the model's
context, so the only decision left is which one to call. Installing both is the
normal case rather than a contradiction: the skill is for writing code against
Oracle-X, the tools are for asking it questions.

## Configure

```bash
export ORACLE_X_URL=http://localhost:8000   # default; set for a remote instance
export ORACLE_X_TOKEN=...                   # only for chat and watchlist
```

Most of the surface is open on a default instance. The token is a Supabase
access token and is needed only for endpoints scoped to a person — see
[`references/auth.md`](references/auth.md).

## What is inside

```
SKILL.md                # the decision table: which question → which endpoint
references/
├── endpoints.md        # generated — every allowlisted endpoint, in full
├── auth.md             # tokens: obtaining, using, verifying
└── recipes.md          # the multi-step reads worth knowing
examples/               # runnable httpx clients
```

`SKILL.md` loads whenever the skill triggers, so it holds only what an agent
needs to choose correctly. The `references/` files are read on demand — the
endpoint reference alone is 800 lines and has no business in context until a
call actually needs it.

## The rule worth knowing before the first call

Oracle-X declines rather than guesses: 404 when a symbol cannot be resolved,
503 when an upstream is dead and an empty list would be a lie. A refusal is an
answer, and passing it on unchanged is the point — in a trading terminal a
plausible wrong number is worse than an error. `SKILL.md` spends a section on
this, and the examples under `examples/` show the difference between "no data"
and "the lookup never happened".

## Source

Generated and maintained in
[Yigtwxx/OracleX](https://github.com/Yigtwxx/OracleX/tree/main/agent-skill).
The endpoint reference is regenerated from the backend's OpenAPI schema and CI
fails if the committed copy has drifted, so it cannot silently describe routes
the API no longer serves.
