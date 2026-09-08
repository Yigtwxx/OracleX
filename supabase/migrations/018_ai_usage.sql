-- ═══════════════════════════════════════════════════════════════════════════════
-- ORACLE-X AI USAGE
--
-- One row per model call. Nothing measured what the terminal actually spends:
-- `profiles.ai_queries_today` counts a route no client has ever called, and the
-- token figures every provider already returns were read only by Ollama's
-- truncation warning and thrown away everywhere else.
--
-- `user_id` is nullable on purpose and that is the most useful column here. The
-- schedulers — the two-minute news scan, the BIST radar voice pass, symbol
-- detection — carry no reader, and on a self-hosted install they are most of
-- the spend. Recording them as NULL rather than dropping them is what makes the
-- difference between "what did I use" and "what does this box use" answerable
-- from the same table.
--
-- `key_owner` says who paid. A reader with their own key costs the operator
-- nothing, so totals that mix the two answer neither question.
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ai_usage (
    id                BIGSERIAL PRIMARY KEY,
    -- SET NULL rather than CASCADE: a deleted account should not silently
    -- rewrite what the install was measured to have spent.
    user_id           UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    -- Which surface asked. "background" for anything with no reader behind it.
    feature           TEXT NOT NULL DEFAULT 'unknown',
    provider          TEXT NOT NULL DEFAULT '',
    model             TEXT NOT NULL DEFAULT '',
    -- 'user' when the caller's own key paid for it, 'server' otherwise.
    key_owner         TEXT NOT NULL DEFAULT 'server',
    -- Nullable, not zero: a provider that reports no usage is a different fact
    -- from one that used no tokens, and averaging zeros would hide it.
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    total_tokens      INTEGER,
    -- Round-trip latency in milliseconds.
    duration_ms       INTEGER,
    ok                BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Every read is "this user, this window", newest first.
CREATE INDEX IF NOT EXISTS idx_ai_usage_user_created
    ON ai_usage (user_id, created_at DESC);

-- The install-wide view the admin overview wants, and the sweep that trims old
-- rows, both scan by time alone.
CREATE INDEX IF NOT EXISTS idx_ai_usage_created
    ON ai_usage (created_at DESC);

-- ═══════════════════════════════════════════════════════════════════════════════
-- ROW LEVEL SECURITY
-- Defence in depth: the backend uses the service-role key and bypasses these,
-- so the real enforcement is get_current_user in dependencies/auth.py.
--
-- Read-only for the owner. There is deliberately no INSERT policy for a signed
-- in reader: rows are written by the server as it makes the calls, and a client
-- that could insert here could inflate or forge its own usage.
-- ═══════════════════════════════════════════════════════════════════════════════

ALTER TABLE ai_usage ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    CREATE POLICY "Users can view own ai usage"
        ON ai_usage FOR SELECT USING (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
