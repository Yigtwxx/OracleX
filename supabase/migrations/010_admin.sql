-- ═══════════════════════════════════════════════════════════════════════════════
-- 010 — ADMIN: suspensions and an audit trail
-- Bu SQL'i Supabase Dashboard > SQL Editor'da çalıştır.
--
-- Non-destructive and re-runnable: every statement is IF NOT EXISTS or an
-- idempotent UPDATE. There are no DROPs.
--
-- Nothing here is enforced by the database. The backend holds the service-role
-- key and bypasses RLS, so `banned_until` is honoured by dependencies/auth.py
-- and by nothing else. Adminship itself is NOT stored here — it lives in the
-- ADMIN_EMAILS environment variable, so a write to this database can never
-- promote anyone.
-- ═══════════════════════════════════════════════════════════════════════════════

-- ── 1. Suspension columns on profiles ────────────────────────────────────────

ALTER TABLE profiles
  ADD COLUMN IF NOT EXISTS banned_until TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS ban_reason   TEXT,
  ADD COLUMN IF NOT EXISTS banned_at    TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS banned_by    UUID REFERENCES auth.users(id) ON DELETE SET NULL;

COMMENT ON COLUMN profiles.banned_until IS
  'NULL means not suspended. A future timestamp means suspended until then — a '
  'suspension lifts itself, no cron job required. A permanent ban is stored as a '
  'far-future date rather than a separate boolean, so one comparison answers '
  'both questions.';

-- Partial index: only suspended rows are indexed, so the overwhelmingly common
-- NULL case costs nothing to maintain.
CREATE INDEX IF NOT EXISTS profiles_banned_until_idx
  ON profiles (banned_until) WHERE banned_until IS NOT NULL;

-- The admin user list sorts on this by default.
CREATE INDEX IF NOT EXISTS profiles_created_at_idx ON profiles (created_at DESC);

-- ── 2. Audit log ─────────────────────────────────────────────────────────────
-- Worth its keep even with a single admin: `banned_until` and
-- `subscription_plan` are overwritten in place and a post delete is a hard
-- delete that cascades its comments and votes away. When someone asks why their
-- post disappeared, the metadata snapshot here is the only surviving record.

CREATE TABLE IF NOT EXISTS admin_audit_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id    UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    -- Denormalised on purpose: the entry has to stay readable after the FK
    -- above is nulled out by a deleted account.
    actor_email TEXT,
    action      TEXT NOT NULL,
    target_type TEXT NOT NULL,
    -- TEXT, not UUID: the row this points at is frequently already gone.
    target_id   TEXT,
    reason      TEXT,
    metadata    JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE admin_audit_log DROP CONSTRAINT IF EXISTS admin_audit_log_action_check;
ALTER TABLE admin_audit_log
  ADD CONSTRAINT admin_audit_log_action_check
  CHECK (action IN ('user.ban', 'user.unban', 'user.plan', 'post.delete', 'comment.delete'));

ALTER TABLE admin_audit_log DROP CONSTRAINT IF EXISTS admin_audit_log_target_type_check;
ALTER TABLE admin_audit_log
  ADD CONSTRAINT admin_audit_log_target_type_check
  CHECK (target_type IN ('user', 'post', 'comment'));

CREATE INDEX IF NOT EXISTS admin_audit_log_created_at_idx
  ON admin_audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS admin_audit_log_target_idx
  ON admin_audit_log (target_type, target_id);

-- RLS on with no policy at all: anon and authenticated can read nothing. The
-- backend connects with the service-role key, bypasses RLS, and is the only
-- reader and writer.
ALTER TABLE admin_audit_log ENABLE ROW LEVEL SECURITY;

-- ── 3. Backfill profiles.email ───────────────────────────────────────────────
-- The admin user search filters on this column. Rows created before
-- handle_new_user() existed — or by any path that skipped it — have it NULL.

UPDATE profiles p
   SET email = u.email
  FROM auth.users u
 WHERE p.id = u.id
   AND u.email IS NOT NULL
   AND (p.email IS NULL OR p.email = '');

-- ── 4. Admin RPCs ────────────────────────────────────────────────────────────
-- The user list needs a search, a filter, a sort, a page, per-user post and
-- comment counts, and a total — six things PostgREST cannot do in one call, and
-- the counts in particular would otherwise be one query per row.
--
-- Doing it here also closes a filter-injection hole: `p_search` is a bound
-- parameter, whereas PostgREST's `.or_("email.ilike.%q%,...")` takes a raw
-- filter string that a `,` or `(` in the search box could restructure.

CREATE OR REPLACE FUNCTION get_admin_users(
  p_user_id UUID    DEFAULT NULL,
  p_search  TEXT    DEFAULT NULL,
  p_plan    TEXT    DEFAULT NULL,
  p_status  TEXT    DEFAULT 'all',        -- all | active | banned
  p_sort    TEXT    DEFAULT 'created_at', -- created_at | email | subscription_plan
  p_order   TEXT    DEFAULT 'desc',       -- asc | desc
  p_limit   INTEGER DEFAULT 50,
  p_offset  INTEGER DEFAULT 0
)
RETURNS TABLE (
  id                      UUID,
  email                   TEXT,
  full_name               TEXT,
  avatar_url              TEXT,
  subscription_plan       TEXT,
  subscription_expires_at TIMESTAMPTZ,
  created_at              TIMESTAMPTZ,
  banned_until            TIMESTAMPTZ,
  ban_reason              TEXT,
  posts_count             BIGINT,
  comments_count          BIGINT,
  total_count             BIGINT
)
LANGUAGE sql
STABLE
AS $$
  WITH matched AS (
    SELECT p.*
      FROM profiles p
     WHERE (p_user_id IS NULL OR p.id = p_user_id)
       AND (
         p_search IS NULL OR p_search = ''
         OR p.email     ILIKE '%' || p_search || '%'
         OR p.full_name ILIKE '%' || p_search || '%'
       )
       AND (p_plan IS NULL OR p.subscription_plan = p_plan)
       AND (
         p_status = 'all'
         OR (p_status = 'banned' AND p.banned_until IS NOT NULL AND p.banned_until > NOW())
         OR (p_status = 'active' AND (p.banned_until IS NULL OR p.banned_until <= NOW()))
       )
  )
  SELECT
    m.id, m.email, m.full_name, m.avatar_url,
    m.subscription_plan, m.subscription_expires_at, m.created_at,
    m.banned_until, m.ban_reason,
    COALESCE(po.n, 0) AS posts_count,
    COALESCE(co.n, 0) AS comments_count,
    (SELECT COUNT(*) FROM matched) AS total_count
  FROM matched m
  LEFT JOIN (
    SELECT user_id, COUNT(*) AS n FROM community_posts GROUP BY user_id
  ) po ON po.user_id = m.id
  LEFT JOIN (
    SELECT user_id, COUNT(*) AS n
      FROM community_comments WHERE deleted_at IS NULL GROUP BY user_id
  ) co ON co.user_id = m.id
  -- One CASE arm per (column, direction). Verbose, but it keeps the sort keys
  -- typed — a single CASE cannot return both a timestamptz and a text.
  ORDER BY
    CASE WHEN p_sort = 'email'             AND p_order = 'asc'  THEN lower(m.email)        END ASC  NULLS LAST,
    CASE WHEN p_sort = 'email'             AND p_order = 'desc' THEN lower(m.email)        END DESC NULLS LAST,
    CASE WHEN p_sort = 'subscription_plan' AND p_order = 'asc'  THEN m.subscription_plan   END ASC  NULLS LAST,
    CASE WHEN p_sort = 'subscription_plan' AND p_order = 'desc' THEN m.subscription_plan   END DESC NULLS LAST,
    CASE WHEN p_sort = 'created_at'        AND p_order = 'asc'  THEN m.created_at          END ASC  NULLS LAST,
    CASE WHEN p_sort = 'created_at'        AND p_order = 'desc' THEN m.created_at          END DESC NULLS LAST,
    m.created_at DESC
  LIMIT GREATEST(p_limit, 1) OFFSET GREATEST(p_offset, 0);
$$;

-- The content browser: every post with its author's email, newest first, with a
-- search across title and body. `get_community_feed` cannot serve this — it has
-- no search and deliberately never exposes an email.
CREATE OR REPLACE FUNCTION get_admin_posts(
  p_search TEXT    DEFAULT NULL,
  p_limit  INTEGER DEFAULT 25,
  p_offset INTEGER DEFAULT 0
)
RETURNS TABLE (
  id              UUID,
  title           TEXT,
  content_preview TEXT,
  type            TEXT,
  post_kind       TEXT,
  score           INTEGER,
  comments_count  INTEGER,
  created_at      TIMESTAMPTZ,
  author_id       UUID,
  author_name     TEXT,
  author_email    TEXT,
  total_count     BIGINT
)
LANGUAGE sql
STABLE
AS $$
  WITH matched AS (
    SELECT p.*
      FROM community_posts p
     WHERE p_search IS NULL OR p_search = ''
        OR p.title   ILIKE '%' || p_search || '%'
        OR p.content ILIKE '%' || p_search || '%'
  )
  SELECT
    m.id, m.title,
    left(m.content, 240) AS content_preview,
    m.type, m.post_kind, m.score, m.comments_count, m.created_at,
    m.user_id AS author_id, pr.full_name AS author_name, pr.email AS author_email,
    (SELECT COUNT(*) FROM matched) AS total_count
  FROM matched m
  LEFT JOIN profiles pr ON pr.id = m.user_id
  ORDER BY m.created_at DESC
  LIMIT GREATEST(p_limit, 1) OFFSET GREATEST(p_offset, 0);
$$;

-- The dashboard counters, one round-trip.
CREATE OR REPLACE FUNCTION get_admin_overview()
RETURNS TABLE (
  total_users    BIGINT,
  banned_users   BIGINT,
  new_users_7d   BIGINT,
  free_users     BIGINT,
  pro_users      BIGINT,
  whale_users    BIGINT,
  total_posts    BIGINT,
  posts_today    BIGINT,
  total_comments BIGINT
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    (SELECT COUNT(*) FROM profiles),
    (SELECT COUNT(*) FROM profiles WHERE banned_until IS NOT NULL AND banned_until > NOW()),
    (SELECT COUNT(*) FROM profiles WHERE created_at >= NOW() - INTERVAL '7 days'),
    (SELECT COUNT(*) FROM profiles WHERE subscription_plan = 'free'),
    (SELECT COUNT(*) FROM profiles WHERE subscription_plan = 'pro'),
    (SELECT COUNT(*) FROM profiles WHERE subscription_plan = 'whale'),
    (SELECT COUNT(*) FROM community_posts),
    (SELECT COUNT(*) FROM community_posts WHERE created_at >= CURRENT_DATE),
    (SELECT COUNT(*) FROM community_comments WHERE deleted_at IS NULL);
$$;

-- These are reachable over PostgREST by anyone holding the anon key, so they
-- must not be callable by an ordinary visitor. Only the service role — which is
-- backend-only and already bypasses RLS — may execute them.
REVOKE EXECUTE ON FUNCTION get_admin_users(UUID, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION get_admin_posts(TEXT, INTEGER, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION get_admin_overview() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION get_admin_users(UUID, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION get_admin_posts(TEXT, INTEGER, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION get_admin_overview() TO service_role;

-- ── 5. The admin account ─────────────────────────────────────────────────────
-- Adminship is not granted here — ADMIN_EMAILS does that. This only gives the
-- account the highest subscription plan.
--
-- `subscription_expires_at` is cleared rather than dated: profile_service
-- .get_subscription() auto-downgrades an expired plan to free, so a whale plan
-- with an expiry would silently revert.

DO $$
DECLARE
  admin_email CONSTANT TEXT := 'yigiterdogan023@gmail.com';
  admin_id    UUID;
BEGIN
  SELECT id INTO admin_id FROM auth.users WHERE lower(email) = admin_email;

  IF admin_id IS NULL THEN
    RAISE NOTICE '010: no account for % — sign up first, then re-run this file', admin_email;
    RETURN;
  END IF;

  -- ON CONFLICT covers both cases in one statement: handle_new_user() will
  -- normally have created the row already, but a profile can be missing if the
  -- trigger was added after the account.
  INSERT INTO profiles (id, email, subscription_plan)
  VALUES (admin_id, admin_email, 'whale')
  ON CONFLICT (id) DO UPDATE
    SET subscription_plan       = 'whale',
        subscription_expires_at = NULL,
        banned_until            = NULL,
        ban_reason              = NULL,
        email                   = COALESCE(profiles.email, admin_email),
        updated_at              = NOW();

  RAISE NOTICE '010: admin account % is on the whale plan', admin_email;
END $$;
