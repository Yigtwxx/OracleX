# Security Policy

## Supported versions

Oracle-X is developed on `main`, and fixes land there. Only the latest release
is supported.

| Version | Supported |
|---------|-----------|
| 1.1.x   | Yes |
| < 1.1   | No — upgrade |

## Reporting a vulnerability

**Do not open a public issue.** Email **yigiterdogan023@gmail.com** with:

- A description of the issue and what an attacker gains from it.
- Steps to reproduce, or a proof of concept.
- The version or commit you tested against.
- Your configuration where it matters — `LLM_PROVIDER`, whether the container
  or a local checkout, whether `SCRAPLING_ALLOW_BROWSER` was on.

You will get an acknowledgement. Please give a reasonable window for a fix
before disclosing publicly, and say up front if you intend to publish on a
schedule.

## Scope

Oracle-X is self-hosted: you run it, and you hold the keys. That shapes what
counts as a vulnerability.

**In scope**

- Anything that lets one authenticated user read or modify another's data.
  `dependencies/auth.py` is the authorization boundary — the backend holds the
  Supabase service-role key and therefore bypasses RLS, so any route that takes
  identity from a client-supplied `user_id` instead of the verified bearer token
  is a real finding.
- Any path that exposes an API key: in a response body, a log line, an
  exception message, or an error page. Per-user keys are Fernet-encrypted at
  rest (`services/secret_box.py`) and must only ever be returned as a hint.
- Server-side request forgery through a user-supplied URL. The news pipeline,
  the link-preview service and the scraper all fetch URLs; `url_guard` exists to
  stop them reaching private address space, and a bypass of it is in scope.
- Injection into anything that reaches a database, a shell or a file path.
- Prompt injection that escalates beyond the reply — that is, content which
  causes the model to reach a tool or a source the user could not reach
  directly. A model persuaded to write something wrong in its own answer is a
  quality problem, not a vulnerability.
- Authentication bypass, session fixation, or token handling flaws.

**Out of scope**

- Anything requiring an attacker to already control the host, the `.env` file,
  or the Supabase project.
- Denial of service through volume against your own instance.
- Missing hardening headers on a service intended to run on `localhost`, absent
  a concrete attack.
- Vulnerabilities in third-party upstreams (CoinGecko, OKX, Yahoo, an LLM
  provider) rather than in how Oracle-X calls them.
- Bad market data or a bad model answer. Report those as ordinary issues.
- Results from an automated scanner with no demonstrated impact.

## Deployment notes

Two configuration mistakes account for most of the real risk:

- **The service-role key is backend-only.** `SUPABASE_SERVICE_ROLE_KEY` bypasses
  row-level security. It must never appear in `frontend/.env.local` or in any
  `NEXT_PUBLIC_*` variable — those are compiled into the client bundle and are
  public by construction. The frontend takes the publishable/anon key.
- **`CORS_ORIGINS` is not decoration.** On a public deployment, set it to your
  own origin. The default is localhost.

If `LLM_KEY_ENCRYPTION_SECRET` is unset, the bring-your-own-key feature is
disabled outright rather than falling back to storing keys in plaintext. That is
deliberate; do not work around it.

## What we do

- No secret is committed. `.env`, `*.pem`, `*.key` and `secrets/` are
  gitignored, and `.env.example` carries placeholders only.
- Keys are never logged, at any log level, and raw provider responses are kept
  out of exception messages.
- CI runs `ruff`, `pytest`, `tsc` and a production build on every change to
  `main`.
