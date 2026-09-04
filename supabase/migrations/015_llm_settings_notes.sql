-- ═══════════════════════════════════════════════════════════════════════════════
-- ORACLE-X — PER-USER PROVIDER FOR AI NOTES
-- Adds the fourth surface a user can point at their own provider.
--
-- `use_for_notes` covers ai_notes, which is one code path but seventeen call
-- sites: the asset brief, the macro regime read, ownership flow, chain
-- anomalies, and the BIST notes (stock, fund, market, macro, KAP, IPO, VİOP,
-- VİOP map, positioning, financials, ownership). Without it, a user who had
-- switched every available toggle still met the server's model on most pages
-- that show generated prose.
--
-- Defaults to FALSE so an existing row keeps behaving exactly as it did until
-- its owner opts in. Notes are single-flighted on a content fingerprint and
-- cached globally, so the first reader through the lock writes the copy that
-- every later reader — including anonymous ones — collects.
-- ═══════════════════════════════════════════════════════════════════════════════

ALTER TABLE user_llm_settings
    ADD COLUMN IF NOT EXISTS use_for_notes BOOLEAN NOT NULL DEFAULT FALSE;
