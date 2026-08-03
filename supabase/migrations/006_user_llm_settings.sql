-- ═══════════════════════════════════════════════════════════════════════════════
-- ORACLE-X PER-USER LLM SETTINGS
-- Lets each user choose their own AI provider and supply their own API key.
-- The key is stored encrypted (Fernet, see backend/services/secret_box.py);
-- this table never holds plaintext credentials.
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS user_llm_settings (
    user_id         UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    -- Validated in the application against services/llm/presets.PRESETS rather
    -- than a CHECK constraint, so adding a provider never needs a migration.
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL DEFAULT '',
    encrypted_key   TEXT NOT NULL,
    key_hint        TEXT NOT NULL DEFAULT '',
    use_for_chat    BOOLEAN NOT NULL DEFAULT TRUE,
    use_for_news    BOOLEAN NOT NULL DEFAULT FALSE,
    use_for_reports BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ═══════════════════════════════════════════════════════════════════════════════
-- ROW LEVEL SECURITY
-- Defence in depth: the backend uses the service-role key and bypasses these,
-- so the real enforcement is get_current_user in dependencies/auth.py.
-- ═══════════════════════════════════════════════════════════════════════════════

ALTER TABLE user_llm_settings ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    CREATE POLICY "Users can view own llm settings"
        ON user_llm_settings FOR SELECT USING (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE POLICY "Users can insert own llm settings"
        ON user_llm_settings FOR INSERT WITH CHECK (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE POLICY "Users can update own llm settings"
        ON user_llm_settings FOR UPDATE USING (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE POLICY "Users can delete own llm settings"
        ON user_llm_settings FOR DELETE USING (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
