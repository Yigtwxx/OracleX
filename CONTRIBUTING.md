# Contributing to Oracle-X

Thanks for considering it. This document covers how to get the project running,
what the quality gates are, and what a reviewable pull request looks like.

## Table of contents

- [Ways to contribute](#ways-to-contribute)
- [Development setup](#development-setup)
- [Project layout](#project-layout)
- [Quality gates](#quality-gates)
- [Coding standards](#coding-standards)
- [Commit messages](#commit-messages)
- [Pull requests](#pull-requests)
- [Reporting bugs](#reporting-bugs)
- [Security issues](#security-issues)
- [Adding an LLM provider](#adding-an-llm-provider)
- [Licence](#licence)

## Ways to contribute

- **Bug reports.** A reproducible report is worth more than a patch that fixes a
  symptom. See [reporting bugs](#reporting-bugs).
- **Tests for existing behaviour.** Several endpoints are covered only by manual
  checks. Pinning current behaviour is welcome on its own.
- **New data sources and providers.** Adding an LLM provider is usually a row in
  a table — see [below](#adding-an-llm-provider).
- **Documentation.** If something in the README sent you the wrong way, that is
  a bug in the README.

Before starting anything large, open an issue describing the approach. It is
easier to redirect a paragraph than a branch.

## Development setup

Prerequisites: Python 3.11, Node 18.17+ (CI builds on 20), Git. Ollama is
optional — only needed for `LLM_PROVIDER=ollama`.

```bash
git clone https://github.com/Yigtwxx/OracleX.git
cd OracleX

cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
# Fill in the Supabase credentials. The backend refuses to start without them;
# every other variable has a working default.

./start.sh          # Windows: start.bat
```

`start.sh` provisions the virtualenv, frees ports 8000 and 3100, starts both
servers and seeds the RAG index. To do it by hand, see
[Installation](README.md#installation).

### Python environment

The backend has two requirement layers:

| File | Contents |
|---|---|
| `requirements-base.txt` | Everything the application imports. Neither of the others restates it. |
| `requirements.txt` | `-r requirements-base.txt` plus chromadb, sentence-transformers and scrapling — roughly a gigabyte, all imported lazily. |
| `requirements-dev.txt` | `-r requirements-base.txt` plus pytest, respx and ruff. What CI installs. |

For work that touches the vector store or the scraper, install both:

```bash
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
```

**If you add a dependency**, put it in `requirements-base.txt` unless it is
large *and* can be imported lazily inside the function that needs it. A
top-level import of a package that is only in `requirements.txt` breaks CI at
collection, which reports as an unrelated wall of import errors.

### Supabase

Apply `supabase/migrations/*.sql` in order via the SQL editor or the Supabase
CLI. Without them the auth-gated pages render but do not persist. Migrations are
applied manually; there is no automatic runner.

Because nothing records which files have run, a migration in the repo is not
evidence that its schema is live — and the failure is quiet: the backend boots,
the page renders, and only the write fails. Check the project instead of
assuming:

```bash
cd backend && python scripts/verify_migrations.py
```

A new migration takes the next free number. Do not leave gaps in the sequence:
the verifier flags one, because a gap normally means a migration was applied to
a project and then never committed.

## Project layout

The full tree is documented in
[Directory Structure](README.md#directory-structure). The short version:

```
backend/
  routers/     one module per URL prefix, full paths inline, no prefixes
  services/    business logic; routers stay thin
  prompts/     prompt templates as Markdown with {{placeholder}} substitution
  tests/       pytest, one module per behaviour
frontend/
  app/(app)/         the terminal
  app/(marketing)/   the public landing page at /
  components/  colocated by feature
  lib/         pure logic — this is where the tested code lives
  hooks/       React Query keys and typed hooks
```

Two rules worth stating explicitly:

- **Prompts are not code.** They live in `backend/prompts/**.md` so they can be
  reviewed and tuned without a Python change.
- **Arithmetic does not go to the model.** Anything countable is computed in
  Python and passed in. `analysis_data.py` is the reference for this.

## Quality gates

CI (`.github/workflows/ci.yml`) runs on every push and pull request to `main`.
Run the same commands before you open one:

```bash
# Backend — the first three are CI; ruff format is enforced by pre-commit.
cd backend
ruff check .
python -m compileall -q -x "venv|data" .
pytest
ruff format --check .

# Frontend
cd frontend
npm run lint
npm run typecheck
npm test
npm run build
```

`pre-commit` wires the same tools to your commits:

```bash
pip install pre-commit && pre-commit install
pre-commit run --all-files
```

Note that `npm run build` and a running `npm run dev` share `.next` and will
corrupt each other. Stop the dev server before building.

## Coding standards

### Python

- Type annotations on function signatures.
- `ruff` for both linting and formatting, line length 100 (`pyproject.toml`).
- `async def` throughout; blocking work goes to a thread pool. The event loop is
  shared with a WebSocket fan-out and a scheduler, and stalling it is visible to
  users.
- Outbound HTTP goes through `services/http_client.py`, not a fresh client.
- Secrets come from the environment. Never hardcode a key, never log one, and
  never include a raw provider response in an exception message.

### TypeScript

- `strict: true`. No `any` that a real type would do.
- `prettier` for formatting.
- Server state belongs to React Query with a key in `hooks/queries.ts`; client
  state belongs to Zustand. Adding a third state mechanism needs a reason.
- Styling is Tailwind against the token system in `globals.css` and
  `tailwind.config.ts`. Do not introduce a raw hex colour — add a token.

### Comments

Comments should explain *why*, not restate *what*. A comment that says what the
next line does is noise; a comment recording the constraint that made the code
look strange is the most valuable thing in the file.

### Hardware

Any code that selects a compute device must prefer CUDA, then MPS, then CPU, and
must never hardcode one. The reranker in `services/rag_rerank.py` is the
reference implementation.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <summary in the imperative, under 72 characters>

<body: why the change was made, not what changed — the diff already
says what changed>
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `style`, `perf`.

Split unrelated work into separate commits. Generated data files
(`backend/data/**`) should never ride along with a code change; the scheduler
rewrites them continuously and they will bury the diff.

## Pull requests

1. Branch off `main` — `git checkout -b feat/your-feature`.
2. Keep the branch focused. One reviewable idea per pull request.
3. Run the gates above.
4. Open the pull request against `main`.

In the description, state:

- What changed and why.
- What you verified, and how. If an endpoint has no automated coverage,
  exercise it against `http://localhost:8000/docs` and say what you checked.
- Screenshots or a short recording for any UI change.
- Any new environment variable, with its default and what happens when it is
  absent. Features whose key is missing must switch off, not crash.

## Reporting bugs

Open an issue with:

- What you expected and what happened instead.
- Steps to reproduce, from a clean start if possible.
- Your OS, Python and Node versions, and which `LLM_PROVIDER` you were running.
- Relevant log output — with any API key redacted.

For a data-quality problem (a wrong price, a headline filed under the wrong
ticker), include the symbol, the timestamp and the endpoint you called. Those
are reproducible; "the numbers look wrong" is not.

## Security issues

Do not open a public issue for a vulnerability. Email
**yigiterdogan023@gmail.com** with a description and, if you have one, a proof
of concept. You will get an acknowledgement.

Things worth reporting: anything that lets one user read or modify another's
data, anything that exposes a key, and any way to reach an internal address
through a user-supplied URL. `dependencies/auth.py` is the authorization
boundary — the backend holds the service-role key and therefore bypasses RLS, so
a route that trusts a client-supplied `user_id` is a real finding.

## Adding an LLM provider

If the provider speaks the OpenAI chat-completions format — most do — this is
one row, not new code:

1. Add the row to `backend/services/llm/presets.py`: adapter, base URL, default
   model, and the environment variable holding the key.
2. Add the key to `backend/.env.example`, empty.
3. Add a test alongside the existing provider tests covering how it reports a
   rate limit. That is the part that differs between providers and the part that
   breaks.

If it does not speak that format, it needs an adapter in `providers.py`. There
are two precedents there: Ollama's native API and Anthropic's `/v1/messages`.

## Licence

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE) that covers the project.
