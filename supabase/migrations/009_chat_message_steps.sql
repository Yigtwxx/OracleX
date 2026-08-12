-- ORACLE-X CHAT MESSAGE STEPS
-- Run this in Supabase SQL Editor
--
-- A chat turn now reports what it did — which tools it ran, how each one ended,
-- how long each took — and the UI shows that as a timeline above the answer.
-- Without somewhere to keep it, the timeline exists only until the page
-- reloads, and a reopened conversation shows answers with no account of where
-- they came from.
--
-- JSONB rather than a child table: the steps are only ever read as a whole,
-- alongside the message they belong to, and are never queried across messages.
-- A join would buy nothing and cost a second round trip on every history load.

-- 1. Add the column. An ALTER that adds a nullable column does not rewrite the
--    table and does not touch the existing RLS policies — messages written
--    before this migration simply have NULL, which the client already renders
--    as "no timeline", exactly as it does for the response mode.
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS steps JSONB;

-- 2. Only assistant messages ever carry steps; a user message has nothing to
--    report. Left as a comment rather than a CHECK constraint so that a future
--    turn shape is not blocked by a rule written today.
COMMENT ON COLUMN chat_messages.steps IS
    'Tool steps that produced an assistant message: [{id, tool, label, status, detail, duration_seconds}]. NULL for user messages and for turns predating the timeline.';
