-- ═══════════════════════════════════════════════════════════════════════════════
-- ORACLE-X PER-USER DATA PROVIDER KEYS
-- Lets each reader supply their own key for the optional market-data upstreams
-- (TCMB EVDS, Coinalyze) instead of relying on the server's .env value.
--
-- Same Fernet box as user_llm_settings (backend/services/secret_box.py), so a
-- single LLM_KEY_ENCRYPTION_SECRET covers both; this table never holds
-- plaintext credentials.
--
-- One row per (user, provider) rather than a column per provider: these are
-- optional upstreams that come and go, and a new one should cost a preset entry
-- in services/data_provider_presets.py, not a migration.
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS user_data_provider_keys (
    user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    -- Validated in the application against DATA_PROVIDERS rather than a CHECK
    -- constraint, for the reason above.
    provider      TEXT NOT NULL,
    -- Blank is the "cleared" sentinel, never NULL — matches user_llm_settings.
    encrypted_key TEXT NOT NULL DEFAULT '',
    key_hint      TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (user_id, provider)
);

-- No secondary index: user_id leads the composite primary key, and every query
-- here is either that whole key or a prefix scan on it.

-- ═══════════════════════════════════════════════════════════════════════════════
-- ROW LEVEL SECURITY
-- Defence in depth: the backend uses the service-role key and bypasses these,
-- so the real enforcement is get_current_user in dependencies/auth.py.
-- ═══════════════════════════════════════════════════════════════════════════════

ALTER TABLE user_data_provider_keys ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    CREATE POLICY "Users can view own data provider keys"
        ON user_data_provider_keys FOR SELECT USING (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE POLICY "Users can insert own data provider keys"
        ON user_data_provider_keys FOR INSERT WITH CHECK (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE POLICY "Users can update own data provider keys"
        ON user_data_provider_keys FOR UPDATE USING (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE POLICY "Users can delete own data provider keys"
        ON user_data_provider_keys FOR DELETE USING (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
