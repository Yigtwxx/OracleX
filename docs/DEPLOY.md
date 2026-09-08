# Deploying Oracle-X

For putting this on a server someone else runs. It assumes a Linux host with
Docker, a domain, and nothing else.

The README covers running it on a laptop. This covers the parts that only bite
on a real deployment, and it is ordered so that following it top to bottom
works — several of the steps are only correct in this order.

---

## What you are deploying

Two containers behind a third:

| Container | What it is | Port |
|---|---|---|
| `backend` | FastAPI, one uvicorn worker | 8000, internal |
| `frontend` | Next.js standalone server | 3100, internal |
| `caddy` | TLS, and the only thing the internet reaches | 80, 443 |

State lives in two named volumes: `backend-data` (Chroma vector stores, the
watchlist, analysis reports, liquidation history) and `caddy-data`
(certificates). Everything else is rebuilt from the images.

**The backend runs a single worker on purpose.** `scheduler_service` holds an
APScheduler instance, `websocket_service` a price-streaming singleton, and
`analysis_jobs` an in-process registry. A second worker would duplicate every
scheduled job and split the job registry in half, so scaling means one
container, not more workers. If you need capacity, give the box more CPU.

---

## 1. DNS first

Point an `A` record at the server and let it propagate **before** you start the
stack. Caddy proves control of the domain to Let's Encrypt on the first request;
if the name does not resolve to this host yet, issuance fails, and Let's Encrypt
rate-limits repeated failures. Check from the server itself:

```bash
dig +short your.domain      # must print this server's public IP
```

Open 80 and 443. Port 80 is not optional — it carries the ACME challenge and the
HTTP→HTTPS redirect.

---

## 2. Configuration

```bash
git clone https://github.com/Yigtwxx/OracleX.git
cd OracleX
cp .env.example .env
```

Everything below goes in that one file. Compose reads it for both `${VAR}`
interpolation and the backend container's environment.

### Required — the stack will not work without these

| Variable | Notes |
|---|---|
| `SUPABASE_URL` | From the Supabase project settings |
| `SUPABASE_SERVICE_ROLE_KEY` | The backend refuses to start without this; it bypasses RLS, so treat it as a root credential |
| `SUPABASE_KEY` | The anon key |
| `NEXT_PUBLIC_SUPABASE_URL` | Same URL again — this one is baked into the browser bundle |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Same anon key again, for the same reason |
| `DOMAIN` | e.g. `oracle.example.com`. No scheme, no trailing slash |
| `ACME_EMAIL` | Where Let's Encrypt sends expiry warnings |

### The four that are wrong by default on a server

These have working local defaults, which is exactly why they get missed.

```dotenv
# One origin: Caddy serves the frontend at / and the backend under /api and /ws.
NEXT_PUBLIC_API_URL=https://your.domain
NEXT_PUBLIC_WS_URL=wss://your.domain/ws/prices
NEXT_PUBLIC_SITE_URL=https://your.domain
CORS_ORIGINS=https://your.domain

# Caddy is in front, so X-Forwarded-For is trustworthy and is the only way to
# tell callers apart. Left false, every request looks like it came from the
# proxy and all readers share one rate-limit bucket.
TRUST_PROXY_HEADERS=true
```

> **The three `NEXT_PUBLIC_*` values are compiled into the JavaScript the
> browser downloads.** Changing them later needs
> `docker compose build frontend`, not a restart. Get them right now.

### The AI provider

**Ollama will not be running on the server.** The default provider chain points
at `host.docker.internal:11434`, which on a server is nothing. Pick one:

```dotenv
LLM_PROVIDER=mistral
MISTRAL_API_KEY=...
# Optional: tried in order when the primary is unusable.
LLM_FALLBACK_PROVIDERS=groq,gemini
```

Supported names are in `backend/services/llm/presets.py`. A reader can also
supply their own key from **Profile → AI Provider**, which is then used for
their own turns; the server chain here is what everyone else gets, and what the
scheduled jobs always use.

One thing to be ready to answer, because it is the first question a colleague
asks: selecting Ollama in that form does *not* use the Ollama on their laptop
by default. This server is what places the call, so it needs an address it can
reach — a Cloudflare Tunnel, ngrok or Tailscale Funnel address pasted into the
endpoint field. A private or loopback address is refused rather than attempted,
since a server dialling an address a request named is how internal networks get
read. Left blank, the field means "this server's own Ollama", which on a
deployment is usually nothing at all.

### Per-reader API keys

```dotenv
# Encrypts every key a reader saves, before it reaches Supabase.
LLM_KEY_ENCRYPTION_SECRET=
```

Generate one:

```bash
docker run --rm python:3.11-slim sh -c \
  "pip install -q cryptography && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
```

Two things about it:

- **Empty disables the feature.** The profile forms refuse to save rather than
  storing a credential in plaintext.
- **If this deployment shares a Supabase project with another one, the value
  must match.** The rows are shared; a second secret cannot read the first's
  ciphertext, and every reader would have to re-enter their keys. Rotating it is
  not a migration — the old ciphertext becomes permanently unreadable.

### Admin

```dotenv
ADMIN_EMAILS=you@example.com,colleague@example.com
```

Matched against the verified email on the caller's token. Adminship is never
granted from the database, on the reasoning that a request can write the
database and cannot write the environment.

### Optional — features that switch off cleanly without them

Every one of these is safe to leave empty. The affected board still renders and
says what is missing.

| Variable | What you lose without it |
|---|---|
| `COINGECKO_API_KEY` | Anonymous rate limits; the heatmap spends much of its time on 429s |
| `TCMB_EVDS_API_KEY` | Turkish CPI, so every BIST return is nominal rather than real |
| `COINALYZE_API_KEY` | Open-interest history drops from years to ~30 days |
| `SEC_USER_AGENT` | The Ownership board stops refreshing from 13F/Form 4 filings |
| `ETHERSCAN_API_KEY` | On-chain exchange-flow data |
| `SMTP_*`, `ALARM_EMAIL_SECRET` | Email alarms |

`TCMB_EVDS_API_KEY` and `COINALYZE_API_KEY` can also be supplied per reader from
**Profile → Data Providers**. `SEC_USER_AGENT` cannot: the Ownership board is
one shared artifact rebuilt on a schedule, so there is no reader's request to
attach an address to. Format: `AppName/1.0 (you@example.com)`.

---

## 3. Supabase

### Migrations

Migrations in `supabase/migrations/` are **applied by hand**. A file in the repo
is not evidence that it ran, and the failure mode is quiet: the app boots, the
page renders, and only the write fails.

Run each one, in numerical order, in the Supabase SQL editor. Then verify from
the server:

```bash
docker compose run --rm backend python scripts/verify_migrations.py
```

It exits non-zero if a table any migration declares is missing. Do this before
the first real use, not after someone reports a bug.

### Auth, which is configured in Supabase rather than here

Three settings under **Authentication → URL Configuration**, and the default of
each is wrong for a deployment. The app asks Supabase to send readers back to
`window.location.origin`, so it is already correct about the domain — Supabase
is what refuses it.

| Setting | Value |
|---|---|
| Site URL | `https://your.domain` |
| Redirect URLs | `https://your.domain/auth/callback` and `https://your.domain/auth/reset-password` |

A link Supabase will not redirect to falls back to the Site URL, which ships as
`http://localhost:3000`. The failure is entirely on the new reader's side and
looks like nothing at all from the server: they sign up, the mail arrives, they
click it, and their browser tries to reach their own laptop.

Two more things about the first sign-ups:

- **Supabase's built-in mailer sends a handful of messages an hour** and is
  explicitly not for production. Confirmations to a colleague's address will
  quietly stop arriving. Put real SMTP under **Authentication → Emails**, or
  turn off "Confirm email" while you are onboarding a known group of people.
- **Anyone who can reach the page can sign up.** There is no invite list and no
  approval step. If the domain is public and the readers are not, close signups
  in Supabase after the accounts exist, or keep the site behind whatever your
  workplace already uses.

Admin is separate from all of this and comes from `ADMIN_EMAILS`. A colleague
who signs up gets a normal account: every board, their own keys, their own
watchlists and notes, their own usage. What they do not get is the admin panel,
the ownership refresh buttons, the SMTP form and the install-wide usage total.

---

## 4. Start

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml up --build -d
```

The second file is the TLS overlay. It adds Caddy and **removes the published
ports from `backend` and `frontend`** — with a proxy in front, a published 8000
is a way around it, and on a host with a permissive firewall that is a public
backend with no TLS.

Watch the first start; certificate issuance is the step that fails:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml logs -f caddy
```

Then check the app:

```bash
curl -sI https://your.domain | head -1              # 200
curl -s  https://your.domain/api/system/health      # per-category status
```

Leaving off `-f docker-compose.tls.yml` gives you the plain stack on `:8000` and
`:3100` with no TLS. That is the local shape, not a deployment.

---

## 5. Afterwards

**Updating.** `git pull`, then the same `up --build -d`. Apply any new
migrations first and re-run `verify_migrations.py`. If a `NEXT_PUBLIC_*` value
changed, the frontend image must be rebuilt, which `--build` does.

**Backups.** `backend-data` holds everything that is not in Supabase or in the
images:

```bash
# The volume is prefixed with the Compose project name, which defaults to the
# directory you cloned into — so look it up rather than guessing.
VOL=$(docker volume ls -q | grep backend-data)
docker run --rm -v "$VOL:/data" -v "$PWD:/backup" \
  alpine tar czf /backup/backend-data.tgz -C /data .
```

Supabase is backed up by Supabase. `caddy-data` is worth keeping too — losing it
means re-issuing certificates, and Let's Encrypt allows five duplicates a week.

**Watching cost.** **Profile → Usage** shows requests and tokens per reader,
split by surface, provider, and whether the reader's own key or the install's
paid. An admin can also read install-wide totals — background jobs included —
at `GET /api/profile/usage/install`, which on a self-hosted box is where most of
the spend is: the news scan runs every two minutes.

**`docker compose down` keeps the volumes.** `down -v` deletes them. Only use
`-v` when you mean to wipe the vector stores and the certificates.

---

## Things that will waste an afternoon

- **A blank page with a working `/api/system/health`** is almost always a
  `NEXT_PUBLIC_API_URL` still pointing at localhost. The browser is asking your
  laptop for the API. Rebuild the frontend image after fixing it.
- **Every reader hitting the same rate limit** means `TRUST_PROXY_HEADERS` is
  still false, so all requests are attributed to Caddy's address.
- **AI features silently doing nothing** usually means no `LLM_PROVIDER` was
  set, so the chain is still pointing at an Ollama that is not there.
  `GET /api/llm/status` says which providers were skipped and why.
- **A reader's saved key not being used** — check the toggles under
  Profile → AI Provider. Saving a key turns it on for chat; news, reports and
  notes are opt-in, because each of those spends on a schedule or on somebody
  else's behalf. Scheduled jobs always use the server chain, by design, because
  they carry no reader.
- **Certificate issuance failing** is DNS nine times out of ten. `dig +short
  your.domain` from the server, and confirm port 80 is reachable from outside.
