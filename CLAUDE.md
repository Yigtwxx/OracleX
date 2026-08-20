# Oracle-X

A self-hosted financial intelligence terminal: FastAPI backend, Next.js 14
frontend, Supabase for identity and persistence, ChromaDB for the vector
memory, and a provider-agnostic LLM layer that defaults to local Ollama.

This file records what the code cannot tell you on its own. Everything else —
what a function does, how a component renders — read from the source.

## Commands

```bash
./start.sh                      # both servers; handles venv, ports, RAG seed
                                # backend :8000, frontend :3100

cd backend && source venv/bin/activate
python -m pytest                # 1634 tests, ~2min
ruff check . && ruff format --check .

cd frontend
npm test                        # vitest, 260 tests
npm run typecheck               # tsc --noEmit
npm run lint && npm run build

python scripts/build_agent_skill.py --check   # from repo root
```

All four gates run in CI (`.github/workflows/ci.yml`) and all four must be
clean before a commit. `ruff` is configured in `backend/pyproject.toml` with
`line-length = 100`; running it from the repo root picks up defaults instead,
so run it from `backend/`.

## Shape of the code

Requests land in `backend/routers/` and immediately delegate. A router validates
input, calls one service, and shapes the response — it holds no business logic
and no upstream calls. Everything real lives in `backend/services/`, which is
where to look first for any behaviour question.

Two service conventions carry weight:

**Every upstream belongs to a category in `services/health_registry.py`.** The
registry is passive — the HTTP helpers, the exchange client and the database
wrapper report what they already did, and it only remembers. That is why
`/api/system/health` is cheap enough for the frontend's ten-second poll, and why
categories are grouped by what a user would lose rather than by hostname. A new
upstream whose host maps to no category is invisible to the badge: add it to
`CATEGORIES` and go through the shared helpers rather than calling httpx
directly.

**The LLM layer is a chain, not a client.** `services/llm/` resolves an ordered
list of providers so one outage is not the terminal's outage. Never call a
provider SDK directly from a service; go through `services/llm`. Prompts live
in `backend/prompts/<domain>/` as files, never inline in Python.

The frontend mirrors this. `hooks/` holds the API bindings — `queries.ts` for
the market surface, plus a hook per domain (`useProfile`, `useSocial`,
`useSystemHealth`, …). `lib/` holds pure formatting and derivation logic, which
is where the vitest suite is concentrated because that is where a failure would
be silent rather than loud. Components stay presentational.

## Authorization is in the application layer

The backend talks to Supabase with the **service role key**, which bypasses Row
Level Security. Supabase therefore provides no per-user protection here.

Every user-scoped endpoint must depend on `get_current_user` from
`dependencies/auth.py` and take the caller's identity from the returned
`AuthUser`. A `user_id` arriving in a path, query or body is untrusted and must
never be used to select or mutate rows. `get_current_user` is also the single
choke point that refuses suspended accounts, which is why it cannot be
bypassed "just this once" on a new route.

Admin status comes from the `ADMIN_EMAILS` environment variable rather than a
database column, on the reasoning that a request can write the database and
cannot write the environment.

## Things that will waste your time if you assume otherwise

**Migrations are applied by hand.** A file in `supabase/migrations/` is not
evidence that it ran against the live project. Before debugging anything that
looks like a schema problem, verify against the actual database —
`backend/scripts/verify_migrations.py` exists for this.

**The local model is the constraint, and it is not going to change.** The
default provider chain runs free Ollama models. Quality improvements have to
come from prompts, retrieval and structure, not from reaching for a bigger
model.

**`backend/data/*.json` is mostly generated.** The registry and cache files are
rewritten on every run and are gitignored; a handful of seed files next to them
(`watchlist.json`, `registry/ownership_entities.json`, `analysis_reports.json`,
…) are hand-maintained and tracked. Check `.gitignore` before adding a file
there, and never `git add -A` right after running the backend.

**The API declines rather than guessing.** `/api/price` and `/api/technical`
answer 404 when a symbol cannot be resolved instead of emitting a placeholder.
Preserve that. A plausible wrong number in a trading terminal is worse than an
error.

**Symbols carry their venue.** Crypto is `BTCUSDT` or `BINANCE:ETHUSDT`,
equities are the plain ticker. An unprefixed ticker forced down the crypto path
once read AAPL off a tokenised-equity market; the resolution logic is deliberate
and should not be "simplified".

## Style

Python: type annotations on everything, `X | None` over `Optional[X]`,
f-strings, ruff formatter. TypeScript: `strict: true`, prettier.

Docstrings and comments here explain **why**, not what. The existing code
records the reasoning behind a decision — what broke before, what the
alternative cost — and that is the standard to match. A comment restating the
line below it is noise; a comment explaining why the obvious approach was
rejected is the reason the file is maintainable. Write in English, always.

## Agent-facing packaging

Two things wrap this API for outside agents, and both need updating when a
route in their surface changes.

`agent-skill/` holds two AgentSkills. `oracle-x-api/SKILL.md` is hand-written;
its `references/endpoints.md` is generated from the app's OpenAPI schema, so
adding or renaming a route in the allowlist (`ENDPOINT_GROUPS` in
`scripts/build_agent_skill.py`) means regenerating it — CI fails otherwise.
`oracle-x-dev/` documents these conventions for agents working on the code.

`mcp-server/` exposes the same instance as 26 MCP tools. It talks HTTP to a
running backend and imports nothing from it, so it needs no backend changes —
but a route it calls that changes shape breaks it silently, since its tests
never touch the network. Its own gates are `ruff` and `pytest` from
`mcp-server/`.

## Git

One version for the whole repository, declared in `backend/pyproject.toml` and
mirrored in `frontend/package.json`, `backend/main.py` and the README badge.
Conventional Commits, imperative subject under 72 characters, and a body that
explains why rather than what. Do not commit, push, tag or open a PR unless
explicitly asked.
