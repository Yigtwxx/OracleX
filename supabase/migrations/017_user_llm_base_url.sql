-- ═══════════════════════════════════════════════════════════════════════════════
-- ORACLE-X PER-USER LLM BASE URL
--
-- Ollama runs on the reader's own machine, not on the server. Until now
-- `build_provider` resolved the Ollama base URL from the server's
-- OLLAMA_BASE_URL for everybody, so a reader on a hosted install who selected
-- "ollama" pointed the *server* at its own unreachable localhost:11434, got a
-- failure, and fell through to the server chain without being told — the
-- silent-wrong-answer shape this codebase exists to avoid.
--
-- This column lets a reader name an endpoint the server can actually reach, so
-- "keep using my own free local model" is a real option rather than one that
-- looks selectable and never works.
--
-- Blank is the default and means "use the server's value", which is what every
-- existing row wants.
-- ═══════════════════════════════════════════════════════════════════════════════

ALTER TABLE user_llm_settings
    ADD COLUMN IF NOT EXISTS base_url TEXT NOT NULL DEFAULT '';
