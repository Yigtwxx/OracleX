-- ORACLE-X CHAT MEMORY
-- Run this in the Supabase SQL Editor.
--
-- What the assistant is allowed to remember about a user between sessions:
-- stated preferences, positions they have mentioned, how they want answers
-- shaped. Deliberately a narrow key/value store rather than free text, because
-- what gets written is proposed by a model and the shape is most of the
-- defence — see `chat_memory_service.ALLOWED_KEYS`.
--
-- Not built on `services/ai_notes.py`, which looks similar and is not: that is
-- a cache of generated notes keyed by a fingerprint of market facts, shared
-- across every user, and it makes its own LLM calls.

CREATE TABLE IF NOT EXISTS chat_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE (user_id, key)
);

ALTER TABLE chat_memory ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users can view own memory' AND tablename = 'chat_memory') THEN
        CREATE POLICY "Users can view own memory" ON chat_memory FOR SELECT USING (auth.uid() = user_id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users can insert own memory' AND tablename = 'chat_memory') THEN
        CREATE POLICY "Users can insert own memory" ON chat_memory FOR INSERT WITH CHECK (auth.uid() = user_id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users can update own memory' AND tablename = 'chat_memory') THEN
        CREATE POLICY "Users can update own memory" ON chat_memory FOR UPDATE USING (auth.uid() = user_id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users can delete own memory' AND tablename = 'chat_memory') THEN
        CREATE POLICY "Users can delete own memory" ON chat_memory FOR DELETE USING (auth.uid() = user_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_chat_memory_user ON chat_memory(user_id);
