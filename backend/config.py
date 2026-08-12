"""
Oracle-X Centralized Configuration

Single source of truth for runtime configuration. Values are read from the
environment (and the local `.env` file) via pydantic-settings, with sensible
defaults so the app keeps working out of the box.

Usage:
    from config import settings
    settings.OLLAMA_BASE_URL
"""

import os
from functools import lru_cache
from typing import List, Optional, Set

from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute path to the backend directory so the .env file is found regardless
# of the current working directory the server is launched from.
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=os.path.join(_BASE_DIR, ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Supabase ────────────────────────────────────────────────────────────
    SUPABASE_URL: Optional[str] = None
    SUPABASE_KEY: Optional[str] = None
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = None

    # ── LLM provider selection ──────────────────────────────────────────────
    # Format: "<provider>" or "<provider>:<model>". Only the first colon splits
    # the two, so Ollama tags survive: "ollama:qwen3.6:35b-a3b".
    # Supported providers are listed in services/llm/presets.py.
    LLM_PROVIDER: str = "ollama"
    # Comma-separated chain tried in order when the primary is unusable
    # (unreachable, bad key, unknown model, or rate-limited past its retries).
    # e.g. "gemini:gemini-2.5-flash,ollama"
    LLM_FALLBACK_PROVIDERS: str = ""
    # Model used when a chain entry omits ":<model>". Kept for backwards
    # compatibility with .env files written before providers were configurable.
    LLM_MODEL: str = "qwen3.6:35b-a3b"
    # Only for LLM_PROVIDER=custom (self-hosted vLLM, LM Studio, LiteLLM proxy).
    LLM_BASE_URL: str = ""
    LLM_MAX_RETRIES: int = 3
    # A provider that answers 429 usually states how long its quota window has
    # left. Waiting that out beats falling back only up to a point; past this
    # many seconds the next provider in the chain is the faster answer.
    # Raising it to 60 lets a free-tier per-minute quota be waited out in full,
    # at the cost of stalling the request for that long.
    LLM_RATE_LIMIT_MAX_WAIT: float = 30.0
    # How long a rate-limited provider is skipped when it gave no delay of its
    # own. Free tiers count rejected calls against the same quota, so retrying
    # immediately deepens the outage instead of ending it.
    LLM_RATE_LIMIT_COOLDOWN: float = 60.0
    # How long a provider is skipped once its *daily* budget is spent. Providers
    # report these as if they were rolling windows — Groq answers a spent
    # per-day token limit with "retry in ~60s" — so believing them means
    # re-probing a dead provider every minute until midnight. Half an hour
    # keeps the noise down while still recovering promptly after a reset.
    LLM_DAILY_QUOTA_COOLDOWN: float = 1800.0

    # ── Market data ─────────────────────────────────────────────────────────
    # CCXT exchange id the live price WebSocket streams from. Reachability is a
    # network property: Binance is blocked in several countries and its
    # load_markets() call fails against fapi.binance.com before any tick
    # arrives. OKX is the default because the liquidation and funding services
    # already rely on it and it answers everywhere this app has been run.
    STREAM_EXCHANGE: str = "okx"
    # Encrypts per-user LLM API keys before they are stored in Supabase.
    # Generate one with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Empty disables per-user keys entirely — a key is never stored in plaintext.
    LLM_KEY_ENCRYPTION_SECRET: str = ""

    # ── Local LLM (Ollama) ──────────────────────────────────────────────────
    # Pull the model once with `ollama pull <model>`. qwen3.6:35b-a3b is an MoE
    # model: top-tier quality with fast inference (~3B active params). Drop to
    # qwen3.5:9b for lower latency, or qwen3.6:27b for a dense alternative.
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    # How long Ollama keeps the model in memory after a request. The default is
    # five minutes; reloading a large model costs tens of seconds, during which
    # every call racing the reload times out. Accepts Ollama's duration syntax
    # ("30m", "1h"), or "-1" to keep it resident until the daemon stops.
    OLLAMA_KEEP_ALIVE: str = "30m"
    # Context window requested from Ollama. Every call site that prompts a local
    # model reads this instead of hardcoding its own value.
    #
    # Ollama truncates an over-long prompt from the FRONT, and /api/generate puts
    # the `system` field first — so an overflow silently deletes the system prompt
    # before it deletes anything else. For these prompts that means the
    # anti-hallucination rules are the first casualty, which is why the hard
    # constraints now live at the tail of the turn prompt (prompts/chat/turn.md)
    # rather than relying on this ceiling alone.
    #
    # Measured against qwen3.6:35b-a3b on an M4 Pro: a ~24.5k-token prompt was
    # evaluated whole, while a larger one was cut to 16386 tokens and lost its
    # opening. Raising this value did not move that ceiling — the server caps by
    # what it can fit — so treat PROMPT_TOKEN_BUDGET, not this, as the real limit.
    LLM_NUM_CTX: int = 32768
    # Ceiling the prompt builder budgets against, in tokens. Deliberately below
    # the measured truncation point so a mis-estimate degrades a low-priority
    # block instead of the system prompt. See services/prompt_budget.py.
    PROMPT_TOKEN_BUDGET: int = 12000

    # ── LLM provider API keys ───────────────────────────────────────────────
    # Only the key for the provider(s) you actually use needs a value. Read from
    # the environment and never logged or returned by any endpoint.
    GROQ_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    TOGETHER_API_KEY: str = ""
    MISTRAL_API_KEY: str = ""
    XAI_API_KEY: str = ""
    CEREBRAS_API_KEY: str = ""
    FIREWORKS_API_KEY: str = ""
    PERPLEXITY_API_KEY: str = ""
    # Used by LLM_PROVIDER=custom.
    LLM_API_KEY: str = ""

    # ── Optional external API keys ──────────────────────────────────────────
    # Etherscan is used for on-chain exchange-flow data; empty disables it.
    ETHERSCAN_API_KEY: str = ""

    # CoinGecko powers the asset universe, the overview and the heatmap. Empty
    # means the anonymous free tier, which works but rate-limits aggressively —
    # the heatmap then renews only a handful of coins' repo data per refresh.
    # A free demo key raises that budget; PLAN="pro" also switches the host.
    COINGECKO_API_KEY: str = ""
    COINGECKO_API_PLAN: str = "demo"  # "demo" | "pro"

    # ── Feature flags ───────────────────────────────────────────────────────
    USE_REAL_API: bool = True
    USE_AI: bool = True

    # Whether the model chooses which tools a chat turn runs. Off by default:
    # the fixed plan is the production path until the planner prompt has been
    # tuned against the local model actually serving chat, and a bad plan costs
    # a whole turn. With it off `chat_planner` still runs and still returns the
    # heuristic plan, so the code path is exercised either way.
    CHAT_PLANNER_ENABLED: bool = False

    # ── Scraping ────────────────────────────────────────────────────────────
    # Whether the scrape ladder may launch a real browser for the handful of
    # hosts that serve a JavaScript shell (see services/scrape_service.py).
    # Costs a browser download via `scrapling install` and ~6-15s per page, so
    # it is opt-in: with this off the ladder still runs, it just cannot read
    # Reddit or X. CI leaves it off — no browser is installed there.
    SCRAPLING_ALLOW_BROWSER: bool = False

    # ── CORS ────────────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins for the frontend.
    CORS_ORIGINS: str = "http://localhost:3100,http://127.0.0.1:3100"

    # ── Request throttling ──────────────────────────────────────────────────
    # Whether `X-Forwarded-For` may be believed when identifying a caller
    # (see dependencies/rate_limit.py).
    #
    # Off by default, and that default is the safe one: if nothing in front of
    # this process rewrites the header, any client can set it to a fresh value
    # per request and every per-IP limit becomes decorative. Turn it on only
    # when a reverse proxy you control is the sole way in.
    TRUST_PROXY_HEADERS: bool = False

    # ── Sign-up email checks ────────────────────────────────────────────────
    # Whether POST /api/auth/email/precheck resolves the address's domain over
    # DNS-over-HTTPS before accepting it (see services/email_guard.py).
    #
    # On by default. Off is for offline development and CI, where the syntax and
    # disposable-domain checks still run but no network call is made — a check
    # that cannot reach a resolver fails open anyway, so this only saves the
    # round-trip and the log noise.
    EMAIL_DNS_CHECK_ENABLED: bool = True

    # ── Admin ───────────────────────────────────────────────────────────────
    # Comma-separated emails that get the admin panel, matched case-insensitively
    # against the *verified* email on the caller's JWT.
    #
    # Adminship deliberately lives here rather than in a `profiles` column: the
    # backend holds the service-role key and bypasses RLS, so anything stored in
    # the database is one bug away from being self-grantable. An environment
    # variable cannot be written by a request.
    #
    # Empty is the safe default — nobody is an admin.
    ADMIN_EMAILS: str = ""

    # ── Direct messages ─────────────────────────────────────────────────────
    # Who is allowed to *send* a DM (see services/social/eligibility.py).
    # Reading and replying inside an existing thread are never gated — the rules
    # exist to stop a fresh throwaway account from spraying strangers, not to
    # trap someone mid-conversation.
    #
    # These are settings rather than constants for one reason: with the rules at
    # their intended values, a brand-new project has *nobody* who can send, so
    # the feature cannot be exercised at all. Lowering the age to 0 in .env is
    # how the flow gets tested without faking rows in auth.users.
    DM_REQUIRE_EMAIL_VERIFIED: bool = True
    # Off by default, and that default is a statement of fact rather than a
    # preference: phone verification needs an SMS provider configured on the
    # Supabase project, and until one is, `phone_confirmed_at` is NULL for every
    # account — so turning this on would refuse everyone. Flip it to true the
    # day Twilio/Vonage is wired up. To exercise the flow for free before then,
    # use the dashboard's Test OTP mapping (a fixed number to a fixed code,
    # no SMS sent).
    DM_REQUIRE_PHONE_VERIFIED: bool = False
    # The "three month old account" rule.
    DM_MIN_ACCOUNT_AGE_DAYS: int = 90
    # Ceiling on messages one account may send per rolling day. Not a spam
    # defence on its own — the eligibility rules above are — but it bounds the
    # damage an account that passed them can do before anyone notices.
    DM_DAILY_SEND_LIMIT: int = 200

    # ── Ownership board ─────────────────────────────────────────────────────
    # A single daily rebuild, not a polling interval: every source behind this
    # board publishes quarterly (13F), monthly (reserves) or on-event (Form 4,
    # on-chain). Polling a filing hourly asks the same question ninety times and
    # learns nothing, while spending rate limits that are shared process-wide.
    OWNERSHIP_REFRESH_HOUR: int = 12
    # "Noon" is a claim about a place. The container runs on UTC, so a naive
    # hour would fire at 15:00 local through summer and 14:00 through winter.
    OWNERSHIP_REFRESH_TIMEZONE: str = "Europe/Istanbul"
    # The daily rebuild above is the whole board. This one is only the sources
    # that actually move between two of them: a coin price reprices a treasury
    # continuously, a wallet balance changes when the wallet is used, and a
    # Form 4 lands within two business days of the trade. Everything else is
    # carried forward from the last full run rather than re-downloaded.
    # 0 disables it and leaves the board on the daily cadence alone.
    OWNERSHIP_LIVE_REFRESH_MINUTES: int = 20
    # SEC requires a declaring User-Agent with a contact address on every
    # request and answers 403 without one; repeated violations are blocked by
    # IP, which would take out the whole deployment. Empty disables the 13F and
    # Form 4 providers rather than risking the ban.
    SEC_USER_AGENT: str = ""

    # ── Background scheduler intervals (minutes) ────────────────────────────
    NEWS_FETCH_INTERVAL_MINUTES: int = 2
    RAG_INDEX_INTERVAL_MINUTES: int = 30
    HEATMAP_REFRESH_INTERVAL_MINUTES: int = 5
    # Live tab. The broadcast probe pulls a megabyte per channel and cannot be
    # asked for less, so its interval is the one real cost lever the feature
    # has — see the arithmetic in `live_stream_service`. Setting it to 0
    # disables the probe entirely: the calendar keeps working and the player
    # falls back to YouTube's own channel embed, which needs no probe at all.
    LIVE_STREAM_PROBE_INTERVAL_MINUTES: int = 3
    LIVE_EVENTS_REFRESH_INTERVAL_MINUTES: int = 15
    # Smallest company whose earnings date earns a calendar row. Below roughly
    # this the print moves one ticker rather than the tape.
    LIVE_EARNINGS_MIN_MARKET_CAP: float = 50_000_000_000

    # ── Heatmap board ───────────────────────────────────────────────────────
    # How many assets the board resolves. Which ones is decided live from the
    # market-cap ranking, so a newly launched token appears on its own.
    HEATMAP_COIN_COUNT: int = 50

    # ── Embedding runtime ───────────────────────────────────────────────────
    # Ceiling on the cores torch may use for embedding work on the CPU
    # fallback; 0 means half of them. Only reached when neither CUDA nor MPS is
    # available, but that is exactly the case where an uncapped torch takes the
    # whole machine and starves every other process on the host.
    EMBEDDING_MAX_CPU_THREADS: int = 0

    # Which model turns text into vectors. "ollama" runs
    # RAG_EMBEDDING_MODEL through the daemon that already serves the chat model —
    # no extra runtime, no API key, and it is multilingual, which the previous
    # model was not. "minilm" restores the old local all-MiniLM-L6-v2 path.
    #
    # Switching this invalidates both Chroma stores: the widths differ (1024 vs
    # 384) and vectors from two models are not comparable. Delete
    # backend/data/rag and backend/data/rag_v2, then POST /api/rag/initialize.
    # `rag_embeddings.assert_store_compatible` reports the mismatch on startup
    # rather than letting it surface as meaningless neighbours.
    RAG_EMBEDDING_BACKEND: str = "ollama"
    RAG_EMBEDDING_MODEL: str = "qwen3-embedding:0.6b"
    # Context window requested for the embedding model — deliberately small and
    # nothing to do with LLM_NUM_CTX.
    #
    # Ollama sizes a model's KV cache from its context window, so leaving this at
    # the server default made a 639 MB embedding model occupy 5.8 GB of unified
    # memory to embed a headline. At 1024 it occupies 1.4 GB, with no loss:
    # chunks are capped at RAG_CHUNK_TOKENS (512) and everything else indexed
    # here is a headline or a one-line event description. Raise it only if
    # RAG_CHUNK_TOKENS goes up — an input past this window is truncated silently.
    RAG_EMBEDDING_NUM_CTX: int = 1024

    # ── RAG retrieval ───────────────────────────────────────────────────────
    # BM25 alongside the vector search, fused by reciprocal rank. The reasoning:
    # a market question is full of tickers, dates and figures ("BTC", "SEC",
    # "$104,230") where an exact lexical hit beats semantic proximity, and that
    # is exactly what embeddings blur.
    #
    # UNPROVEN, and honestly so. On evals/golden_set.jsonl this changes nothing —
    # recall@5 and MRR are identical with it on and off. That set currently
    # exercises only `market_events`, whose documents are generated prose that a
    # paraphrased question matches semantically anyway, and `historical_news`
    # (where tickers and figures actually appear verbatim) is still empty. So the
    # measurement says "no effect here", not "no effect".
    #
    # Kept on because it is cheap and the case for news retrieval is sound, but
    # nobody should assume it is earning its keep until the news collection has
    # content and the eval is re-run. If it still shows nothing then, turn it off.
    RAG_HYBRID_SEARCH: bool = True
    # RRF's damping constant. 60 is the value from the original paper and is not
    # sensitive enough to be worth tuning before there is an eval to tune against.
    RAG_RRF_K: int = 60

    # A cross-encoder reads the query and the document together instead of
    # comparing two independently-produced vectors, which is why it catches
    # relevance that bi-encoder similarity cannot. It only reorders what search
    # already found, so it runs last, over the fused candidate pool.
    #
    # Empty disables it — the heuristic composite score in `rag_scoring` then
    # does the ordering on its own, as it did before.
    RAG_RERANK_MODEL: str = "BAAI/bge-reranker-v2-m3"
    # How many fused candidates the cross-encoder scores. Every one costs a
    # forward pass, so this bounds the latency the reranker can add.
    RAG_RERANK_CANDIDATES: int = 20

    # ── RAG chunking ────────────────────────────────────────────────────────
    # Article bodies are fetched for the news pipeline but were never indexed —
    # only the headline and a truncated summary were, so retrieval could match a
    # headline and never the paragraph that actually explained the move. Bodies
    # are chunked on paragraph boundaries and indexed alongside.
    RAG_CHUNK_TOKENS: int = 512
    RAG_CHUNK_OVERLAP_TOKENS: int = 64

    # ── RAG scoring ─────────────────────────────────────────────────────────
    # How a retrieved past event is ranked. The old code sorted purely by
    # embedding proximity, which answered "is this text nearby" and never "did
    # this event matter". These weights answer the second question.
    #
    # Relevance floor, as a true cosine. Embeddings are unit-normalised, so
    # Chroma's squared-L2 distance is exactly 2 - 2*cos and a genuine cosine is
    # available. Anything below the floor is dropped rather than shown weakly —
    # feeding the model a bad precedent is worse than feeding it none.
    #
    # The floors are PER COLLECTION because one value can no longer serve them
    # all. Measured with scripts/calibrate_rag_relevance.py against
    # qwen3-embedding:0.6b (7 on-topic probes, 5 deliberately off-topic ones):
    #
    #   collection       on-topic min   off-topic max   chosen
    #   market_events        0.497          0.293        0.40
    #   price_history        0.394          0.358        0.38
    #   financial_news       0.538          0.501        0.52
    #
    # A single floor would have to sit at or below 0.394 to keep price history
    # and at or above 0.501 to exclude off-topic news — those cannot both hold.
    # Under the previous model the whole question was moot: on-topic bottomed out
    # at 0.260 against off-topic peaking at 0.220, a gap of 0.04 that no threshold
    # could exploit. The new model's events gap is 0.204.
    #
    # The prices and news gaps are still narrow (~0.036), so each floor is the
    # midpoint of its own measured gap and is expected to admit some marginal
    # matches. That is now much cheaper than it was: the cross-encoder re-ranks
    # everything this floor lets through, so the floor is a cheap pre-filter
    # rather than the last line of defence. Re-run the script as collections grow.
    #
    # What no floor can do is separate *finance but irrelevant* from *finance and
    # relevant* — a dividend announcement and a tariff headline are neighbours in
    # embedding space. Symbol weighting and the reranker handle that, which is why
    # ranking uses the composite score rather than relevance alone.
    RAG_MIN_RELEVANCE: float = 0.38
    RAG_MIN_RELEVANCE_EVENTS: float = 0.40
    RAG_MIN_RELEVANCE_PRICES: float = 0.38
    RAG_MIN_RELEVANCE_NEWS: float = 0.52
    # Half-lives for the recency term, per collection. News goes stale in weeks;
    # a structural event (a halving, a landmark ruling) stays instructive for
    # years, hence the three-year half-life.
    RAG_RECENCY_HALF_LIFE_NEWS_DAYS: float = 90.0
    RAG_RECENCY_HALF_LIFE_EVENTS_DAYS: float = 1095.0
    RAG_RECENCY_HALF_LIFE_PRICES_DAYS: float = 365.0
    # Recency never decays past this. The 2020 halving is old and still the best
    # precedent for a halving question; a pure exponential would bury it.
    RAG_RECENCY_FLOOR: float = 0.25
    # Scale of the magnitude term: weight = 1 - exp(-|pct| / scale). At 6.0 a 5%
    # move scores 0.57, 10% scores 0.81, 20% scores 0.96 — saturating, so a
    # once-in-a-decade crash does not outrank everything else by pure size.
    RAG_MAGNITUDE_SCALE_PCT: float = 6.0
    # Importance weights. Kept summing to 1.0 so the result stays a 0-1 score.
    RAG_WEIGHT_RECENCY: float = 0.30
    RAG_WEIGHT_MAGNITUDE: float = 0.35
    RAG_WEIGHT_CLASS: float = 0.20
    RAG_WEIGHT_SYMBOL: float = 0.15
    # An event whose headline read one way and whose durable outcome went the
    # other is the most instructive precedent there is — it is the case that
    # breaks "lawsuit means the price falls". So it is boosted, not penalised.
    # The smaller boost covers events where only the immediate reaction and the
    # durable outcome disagreed.
    RAG_SURPRISE_BOOST: float = 1.40
    RAG_INVERSION_BOOST: float = 1.25
    # Days after an event at which its outcome is measured. Both canonical
    # reversals need the long end: XRP peaked ~113 days after the SEC suit, and
    # NVDA was still below its pre-DeepSeek price at 90 days but far above it at
    # 365. A set that stops at 90 labels both of them backwards.
    RAG_OUTCOME_HORIZONS_DAYS: str = "1,7,30,90,180,365"
    # Re-ranking can only reorder what was retrieved, so more candidates are
    # pulled than are kept and the surplus is discarded after scoring.
    RAG_CANDIDATE_MULTIPLIER: int = 4

    # ── News symbol attribution ─────────────────────────────────────────────
    # Concurrent LLM calls allowed while working out which asset each headline
    # is about. Every source is fetched at once and a refresh carries ~150
    # items, so without a ceiling the provider is handed the whole batch at
    # once and answers none of it inside the per-call timeout.
    SYMBOL_DETECTION_CONCURRENCY: int = 4

    # ── Logging ─────────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"

    @property
    def cors_origins_list(self) -> List[str]:
        """CORS_ORIGINS parsed into a clean list of origins."""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def admin_emails(self) -> Set[str]:
        """
        ADMIN_EMAILS parsed into a set of lowercased addresses.

        Read through this property at call time, never captured into a
        module-level constant: tests monkeypatch `ADMIN_EMAILS`, and a cached
        copy would also mean a restart is needed to change who is an admin.
        """
        return {e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()}

    @property
    def rag_outcome_horizons(self) -> List[int]:
        """RAG_OUTCOME_HORIZONS_DAYS parsed into a sorted list of day offsets."""
        days = set()
        for part in self.RAG_OUTCOME_HORIZONS_DAYS.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                value = int(part)
            except ValueError:
                continue
            if value > 0:
                days.add(value)
        return sorted(days)

    @property
    def supabase_backend_key(self) -> Optional[str]:
        """Prefer the service-role key for backend operations (bypasses RLS)."""
        return self.SUPABASE_SERVICE_ROLE_KEY or self.SUPABASE_KEY

    def validate_required(self) -> None:
        """
        Fail fast at startup if credentials needed to serve requests are absent.

        Without these, Supabase-backed features (auth, chat, profiles,
        community) raise on first use — a 500 mid-request instead of a clear
        startup error. Auth in particular cannot verify a single token, so the
        app would reject every authenticated request.
        """
        missing = []
        if not self.SUPABASE_URL:
            missing.append("SUPABASE_URL")
        if not self.supabase_backend_key:
            missing.append("SUPABASE_KEY or SUPABASE_SERVICE_ROLE_KEY")

        if missing:
            raise RuntimeError(
                "Missing required configuration: "
                + ", ".join(missing)
                + ". Set them in backend/.env (see .env.example)."
            )


@lru_cache
def get_settings() -> Settings:
    """Return the cached singleton Settings instance."""
    return Settings()


# Convenient module-level singleton.
settings = get_settings()
