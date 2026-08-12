-- ═══════════════════════════════════════════════════════════════════════════════
-- 013 — SOCIAL: direct messages, blocking, and per-user community activity
-- Bu SQL'i Supabase Dashboard > SQL Editor'da çalıştır.
--
-- ⚠  Run 012_profile_social.sql FIRST. The Social tab's Activity section reads
--    community_user_karma() and the Preview section reads profiles.bio, both of
--    which 012 creates. As of 2026-08-12 neither existed in the live project.
--
-- Non-destructive and re-runnable: every statement is IF NOT EXISTS, a
-- CREATE OR REPLACE, or a DROP-then-CREATE on a policy this file owns.
--
-- What arrives here:
--
--   1. `dm_conversations` / `dm_messages` / `dm_reads` — one-to-one direct
--      messages. Read state is per participant, so it is its own table.
--   2. `dm_blocks` — per-person blocking, the escape hatch that makes an
--      open-to-everyone inbox tolerable.
--   3. `user_settings.dm_enabled` — the account-wide "don't message me" switch.
--   4. `community_user_activity()` — the numbers the Activity tab shows,
--      computed on read for the same reason karma is in 012.
--
-- Sending is additionally gated in the application layer on verified email,
-- verified phone and account age; see services/social/eligibility.py. Those
-- rules are env-tunable and deliberately NOT encoded here — a CHECK constraint
-- cannot be relaxed for a test account without a migration.
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── 1. Conversations ─────────────────────────────────────────────────────────
-- The pair is stored in a canonical order (user_a < user_b) rather than as
-- "initiator, recipient". That ordering is what lets a unique index express
-- "at most one conversation per pair": without it, two people opening a thread
-- with each other at the same instant produce two conversations and each sees
-- half the history. Insertion sorts the pair before it writes, so the index
-- turns the race into a harmless duplicate-key that the service re-reads.

CREATE TABLE IF NOT EXISTS dm_conversations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_a          UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  user_b          UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  -- Denormalized so the inbox can sort without touching dm_messages. Kept
  -- current by the trigger below, not by the application.
  last_message_at TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE dm_conversations DROP CONSTRAINT IF EXISTS dm_conversations_ordered;
ALTER TABLE dm_conversations
  ADD CONSTRAINT dm_conversations_ordered CHECK (user_a < user_b);

CREATE UNIQUE INDEX IF NOT EXISTS dm_conversations_pair_idx
  ON dm_conversations (user_a, user_b);

-- The inbox query is "conversations involving me, newest first". Two indexes
-- rather than one because the viewer may be on either side of the pair.
CREATE INDEX IF NOT EXISTS dm_conversations_user_a_idx
  ON dm_conversations (user_a, last_message_at DESC);
CREATE INDEX IF NOT EXISTS dm_conversations_user_b_idx
  ON dm_conversations (user_b, last_message_at DESC);

COMMENT ON TABLE dm_conversations IS
  'One row per unordered pair of members. user_a < user_b is enforced so the unique index can prevent duplicate threads.';

-- ── 2. Messages ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS dm_messages (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES dm_conversations(id) ON DELETE CASCADE,
  sender_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  body            TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Matched by the same cap in the API and the composer's counter. Enforced here
-- too so a direct write cannot store something the UI cannot render.
ALTER TABLE dm_messages DROP CONSTRAINT IF EXISTS dm_messages_body_length_check;
ALTER TABLE dm_messages
  ADD CONSTRAINT dm_messages_body_length_check
  CHECK (char_length(body) BETWEEN 1 AND 2000);

-- Serves both the thread read (newest page first) and the unread count.
CREATE INDEX IF NOT EXISTS dm_messages_conv_idx
  ON dm_messages (conversation_id, created_at DESC);

-- ── 3. Read cursors ──────────────────────────────────────────────────────────
-- A timestamp per participant rather than a per-message read flag: the unread
-- count is "messages after my cursor that I did not send", which is one indexed
-- range scan instead of a row per message per reader.

CREATE TABLE IF NOT EXISTS dm_reads (
  conversation_id UUID NOT NULL REFERENCES dm_conversations(id) ON DELETE CASCADE,
  user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  last_read_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (conversation_id, user_id)
);

-- ── 4. Blocking ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS dm_blocks (
  blocker_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  blocked_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (blocker_id, blocked_id)
);

ALTER TABLE dm_blocks DROP CONSTRAINT IF EXISTS dm_blocks_not_self;
ALTER TABLE dm_blocks
  ADD CONSTRAINT dm_blocks_not_self CHECK (blocker_id <> blocked_id);

-- "Has anyone blocked me?" is asked on every send, from the blocked side.
CREATE INDEX IF NOT EXISTS dm_blocks_blocked_idx ON dm_blocks (blocked_id);

-- ── 5. last_message_at, maintained by the database ───────────────────────────
-- The same reasoning as 007's score triggers: an application-side
-- read-modify-write here would let two concurrent sends leave the inbox sorted
-- by the older of the two.

CREATE OR REPLACE FUNCTION dm_touch_conversation() RETURNS TRIGGER AS $$
BEGIN
  UPDATE dm_conversations
     SET last_message_at = NEW.created_at
   WHERE id = NEW.conversation_id
     AND (last_message_at IS NULL OR last_message_at < NEW.created_at);
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_dm_touch_conversation ON dm_messages;
CREATE TRIGGER trg_dm_touch_conversation
  AFTER INSERT ON dm_messages
  FOR EACH ROW EXECUTE FUNCTION dm_touch_conversation();

-- ── 6. The account-wide opt-out ──────────────────────────────────────────────
-- Defaults TRUE: a switch that starts off is a feature nobody discovers.

ALTER TABLE user_settings
  ADD COLUMN IF NOT EXISTS dm_enabled BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN user_settings.dm_enabled IS
  'When false, nobody may open a conversation with this user or send into an existing one. Existing threads stay readable.';

-- ── 7. Row Level Security ────────────────────────────────────────────────────
-- The backend reaches these tables with the service-role key, which bypasses
-- RLS entirely — authorization is enforced in services/social/. These policies
-- are the second line of defence for the day something reaches the tables with
-- the anon key, and they are written participant-scoped so that day is not an
-- incident. Same posture 012 took for profile_social_links.

ALTER TABLE dm_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE dm_messages      ENABLE ROW LEVEL SECURITY;
ALTER TABLE dm_reads         ENABLE ROW LEVEL SECURITY;
ALTER TABLE dm_blocks        ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Participants read their conversations" ON dm_conversations;
CREATE POLICY "Participants read their conversations"
  ON dm_conversations FOR SELECT TO authenticated
  USING (auth.uid() IN (user_a, user_b));

-- No INSERT/UPDATE/DELETE policy for conversations on purpose: creating one
-- means passing the eligibility gate, which only the backend can evaluate.

DROP POLICY IF EXISTS "Participants read their messages" ON dm_messages;
CREATE POLICY "Participants read their messages"
  ON dm_messages FOR SELECT TO authenticated
  USING (EXISTS (
    SELECT 1 FROM dm_conversations c
     WHERE c.id = dm_messages.conversation_id
       AND auth.uid() IN (c.user_a, c.user_b)
  ));

DROP POLICY IF EXISTS "Users read their own read cursor" ON dm_reads;
CREATE POLICY "Users read their own read cursor"
  ON dm_reads FOR SELECT TO authenticated
  USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users read their own blocks" ON dm_blocks;
CREATE POLICY "Users read their own blocks"
  ON dm_blocks FOR SELECT TO authenticated
  USING (auth.uid() = blocker_id);

-- ── 8. Inbox ─────────────────────────────────────────────────────────────────
-- One round trip for the whole inbox: peer identity, the last message, and the
-- unread count per thread. Assembling this in Python would be a query per
-- conversation for the last message and another for the unread count, and the
-- inbox is the most-polled surface in the feature.
--
-- ⚠  SECURITY DEFINER with `uid` as a parameter means whoever may execute this
--    can read *anyone's* inbox by passing their id. That is why the GRANT below
--    names service_role only, unlike community_user_activity() further down.
--    Do not add `authenticated` to it.

CREATE OR REPLACE FUNCTION dm_inbox(uid UUID)
RETURNS TABLE (
  conversation_id        UUID,
  peer_id                UUID,
  peer_full_name         TEXT,
  peer_avatar_url        TEXT,
  peer_subscription_plan TEXT,
  last_body              TEXT,
  last_sender_id         UUID,
  last_message_at        TIMESTAMPTZ,
  unread_count           INT
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT
    c.id,
    peer.id,
    peer.full_name,
    peer.avatar_url,
    peer.subscription_plan,
    m.body,
    m.sender_id,
    c.last_message_at,
    (SELECT COUNT(*)::INT
       FROM dm_messages u
      WHERE u.conversation_id = c.id
        AND u.sender_id <> uid
        AND u.created_at > COALESCE(r.last_read_at, '-infinity'::TIMESTAMPTZ))
  FROM dm_conversations c
  JOIN profiles peer
    ON peer.id = CASE WHEN c.user_a = uid THEN c.user_b ELSE c.user_a END
  LEFT JOIN dm_reads r
    ON r.conversation_id = c.id AND r.user_id = uid
  -- LATERAL rather than a correlated scalar per column: one index scan on
  -- (conversation_id, created_at DESC) yields both the body and the sender.
  LEFT JOIN LATERAL (
    SELECT body, sender_id
      FROM dm_messages
     WHERE conversation_id = c.id
     ORDER BY created_at DESC
     LIMIT 1
  ) m ON TRUE
  WHERE uid IN (c.user_a, c.user_b)
  ORDER BY c.last_message_at DESC NULLS LAST;
$$;

REVOKE ALL ON FUNCTION dm_inbox(UUID) FROM PUBLIC, authenticated;
GRANT EXECUTE ON FUNCTION dm_inbox(UUID) TO service_role;

COMMENT ON FUNCTION dm_inbox(UUID) IS
  'Backend-only. SECURITY DEFINER and takes the viewer as a parameter, so granting this to authenticated would let anyone read anyone else''s inbox.';

-- The nav badge. Same warning, same grant.
CREATE OR REPLACE FUNCTION dm_unread_total(uid UUID)
RETURNS INT
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT COALESCE(COUNT(*), 0)::INT
    FROM dm_messages m
    JOIN dm_conversations c ON c.id = m.conversation_id
    LEFT JOIN dm_reads r ON r.conversation_id = c.id AND r.user_id = uid
   WHERE uid IN (c.user_a, c.user_b)
     AND m.sender_id <> uid
     AND m.created_at > COALESCE(r.last_read_at, '-infinity'::TIMESTAMPTZ);
$$;

REVOKE ALL ON FUNCTION dm_unread_total(UUID) FROM PUBLIC, authenticated;
GRANT EXECUTE ON FUNCTION dm_unread_total(UUID) TO service_role;

-- ── 9. Activity ──────────────────────────────────────────────────────────────
-- Superset of community_user_karma() from 012, which stays as it is because the
-- public profile only needs the three karma numbers. Same tombstone reasoning:
-- community_posts is hard-deleted so there is nothing to filter, while a
-- tombstoned comment should stop counting toward text nobody can read.
--
-- `best_post_*` are NULL for a member who has never posted; the UI reads that
-- as "no posts yet" rather than rendering a zero.

CREATE OR REPLACE FUNCTION community_user_activity(uid UUID)
RETURNS TABLE (
  post_count       INT,
  comment_count    INT,
  post_karma       INT,
  comment_karma    INT,
  total_karma      INT,
  best_post_id     UUID,
  best_post_title  TEXT,
  best_post_score  INT
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  WITH p AS (
    SELECT COUNT(*)::INT AS n, COALESCE(SUM(score), 0)::INT AS k
      FROM community_posts WHERE user_id = uid
  ),
  c AS (
    SELECT COUNT(*)::INT AS n, COALESCE(SUM(score), 0)::INT AS k
      FROM community_comments WHERE user_id = uid AND deleted_at IS NULL
  ),
  best AS (
    SELECT id, title, score
      FROM community_posts
     WHERE user_id = uid
     ORDER BY score DESC, created_at DESC
     LIMIT 1
  )
  SELECT p.n, c.n, p.k, c.k, p.k + c.k, best.id, best.title, best.score
    FROM p, c LEFT JOIN best ON TRUE;
$$;

GRANT EXECUTE ON FUNCTION community_user_activity(UUID) TO authenticated, service_role;

COMMENT ON FUNCTION community_user_activity(UUID) IS
  'Everything the Social > Activity tab shows, computed on read. Not denormalized onto profiles for the same reason karma is not: a counter column drifts on every deletion and retracted vote.';
