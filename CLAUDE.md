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
python -m pytest                # ~1900 tests, ~2min
ruff check . && ruff format --check .

cd frontend
npm test                        # vitest, ~450 tests
npm run typecheck               # tsc --noEmit
npm run lint && npm run build
npm run e2e                     # playwright, ~15 tests; reuses a running :3100

python scripts/build_agent_skill.py --check   # from repo root
python scripts/build_repo_facts.py --check    # from repo root
```

All of these run in CI (`.github/workflows/ci.yml`) and all of them must be
clean before a commit. `ruff` is configured in `backend/pyproject.toml` with
`line-length = 100`; running it from the repo root picks up defaults instead,
so run it from `backend/`.

The test counts above are rounded on purpose. Exact ones belong in
`frontend/lib/generated/repo-facts.ts`, which is generated from the collectors
and checked by `build_repo_facts.py --check` — a precise figure written by hand
anywhere else is wrong within a release, which is how this file came to claim
1634 backend and 260 frontend tests long after both had grown.

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

**Takasbank's parameters are open; its website is not.** `www.takasbank.com.tr`
sits behind bot protection and will not answer a script, which makes the risk
parameters look unavailable. They are not: `wwwdata.takasbank.com.tr` is a
separate host with an open directory listing and no protection at all, and
`pardosya/Prod/YYMMDD/TAKASEOD_…-001.zip` is the day's SPAN file. Do not use
`wwwdata.takasbank.com.tr/viop/SPAN/` — it is a legacy archive frozen in March
2017 that still serves 200s. Reading it costs two filters: `setlMeth == "DELIV"`
and a `pfCode` that does not end in `_C`, because the file carries a portfolio
per broker and a rights-issue portfolio beside each contract. Skip either and
THYAO's scan range reads 14.0 instead of 13.4.

**VİOP publishes no maintenance margin rate.** The CCP procedure leaves the
level to a General Letter and states maintenance is not applied at end of day,
so the price at which a margin call actually triggers cannot be computed from
anything public. The "75% of initial" figure that circulates appears only in an
undated guide. `viop_margin_map` therefore draws the *scan range* — the move a
position's initial margin was sized for — and the page says in as many words
that this is not a call level. Do not "improve" it by adopting the 75%.

**Polymarket has no trader geography, and its arrays are strings.** Two facts
about the prediction-market surface that look like bugs if you assume otherwise.
The exchange settles on Polygon and identifies a counterparty only by
`proxyWallet`, so no public endpoint anywhere carries a bettor's location — a
"bets by country" view cannot be built, and the map instead draws three layers
that each say what they are (`services/polymarket/map_service.py`). And Gamma
returns `outcomes`, `outcomePrices` and `clobTokenIds` as JSON-encoded *strings*,
so `market["outcomePrices"][0]` is the character `[`. Nothing raises; the board
just fills with plausible nonsense. Everything crossing that boundary goes
through `gamma._maybe_json`.

**The bet analysis is allowed to refuse.** `services/polymarket/sufficiency.py`
decides whether the model is asked for a verdict at all, and below its floors the
endpoint answers with `insufficient_evidence` and names every search that came
back empty. A refusal is a successful run, not an error — do not "fix" it by
lowering the bar or by letting a thin evidence base through. The facts and
microstructure are computed without a model and are served either way, which is
what keeps a refusal from reading as a broken page.

**Borsa İstanbul has no queryable IPO source, and this was tested rather than
assumed.** KAP's disclosure query API answers 404 (`/tr/api/disclosure/byCriteria`
and every sibling; only the *fund* surface in `kap_fund_client` is real), its
company list carries no listing date, and the TradingView scanner backfills a
trailing-year return for all 626 BIST names so "listed within a year" cannot be
inferred either. The rolling tape in `kap_service` is a few days deep and sees no
offering that closed last month. `halkarz_client` therefore reads
`halkarz.com`, a community-maintained calendar with no contract — parsed by
label text rather than DOM position, with every field capped and every failure
recorded per row in `unparsed` so parser rot is countable instead of a board
that quietly empties. The returns the board leads with are computed here from
that offering price and our own scanner quote, so the number a reader acts on is
ours even when the date beside it is not.

**Deflating a level is not deflating a return, and the two live in different
modules.** `real_return.deflate` applies the Fisher relation to a *return* — the
right tool for a post-IPO gain over a window. `services/bist/deflator.py`
restates a *level*: one figure moved from its own quarter's lira into another,
which is a ratio of CPI index values. Using either on the other's input produces
a plausible number that is wrong. Two things about the index itself bite: EVDS
returns an unpadded `2026-6`, so a lookup keyed on `2026-06` misses silently and
every quarter reads as uncovered; and the series runs months behind the
statements — eight months behind when this was written — which is why the
deflation base falls back to the newest quarter the index can actually reach
rather than pinning to the newest quarter on the board and taking the whole page
nominal over one unreachable bar.

**Turkish folding needs the dotless i spelled out.** NFKD decomposes ş, ğ, ç, ö
and ü into a base letter plus a combining mark, so stripping marks folds them. It
does nothing to `ı` (U+0131), which is its own letter rather than an `i` with
something removed. A label map written with plain `i` therefore misses every
Turkish string containing one — "Aracı Kurum" folds to "aracı kurum" and never
matches "araci kurum" — and nothing raises. `halkarz_client._ascii_fold` maps it
explicitly; `services/bist/text.fold` alone is not enough when the comparison
target is ASCII.

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

`agent-skill/` holds three AgentSkills. `oracle-x-api/SKILL.md` and
`oracle-x-bist/SKILL.md` are hand-written; the `references/endpoints.md` beside
each is generated from the app's OpenAPI schema, so adding or renaming a route
in the allowlist (`ENDPOINT_GROUPS` in `scripts/build_agent_skill.py`) means
regenerating both — CI fails otherwise. The allowlist is *partitioned* between
those two by `BIST_GROUP_TITLES`, not copied into both: Borsa İstanbul is a
third of the surface and most installs are not in Turkey, so an agent that will
never ask about VİOP should not carry it. `oracle-x-dev/` documents these
conventions for agents working on the code.

`.claude-plugin/marketplace.json` packages the same three skills plus the MCP
server as Claude Code plugins. Its entries point at `agent-skill/` rather than
copying it, so there is one copy of each skill. Three things about that format
bite silently and are recorded in `plugins/README.md`: component specs must
live in exactly one place, `skills` paths resolve against the entry's `source`,
and `mcpServers` is honoured inline but ignored as a path.

`mcp-server/` exposes the same instance as 36 MCP tools. It talks HTTP to a
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
