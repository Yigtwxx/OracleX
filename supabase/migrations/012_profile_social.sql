-- ═══════════════════════════════════════════════════════════════════════════════
-- 012 — PROFILE: self-declared social links, a bio, and derived karma
-- Bu SQL'i Supabase Dashboard > SQL Editor'da çalıştır.
--
-- Non-destructive and re-runnable: every statement is IF NOT EXISTS, a
-- CREATE OR REPLACE, or a DROP-then-CREATE on a policy this file owns.
--
-- Four things arrive here:
--
--   1. `profiles.bio` and `profile_social_links` — the feature itself. These
--      links are self-declared. Nothing in this schema asserts that a handle
--      belongs to the person who typed it, and no UI may imply otherwise.
--      Supabase's manual identity linking would make them provable, but
--      proving ownership is not what the feature is for.
--   2. `community_user_karma()` — karma computed on read. A counter column on
--      `profiles` would drift the first time a post was deleted or a vote
--      retracted, and no trigger would notice.
--   3. The three storage policies from 011. That migration was never run
--      against the live project, which is why avatar uploads failed with
--      "Bucket not found" until the bucket was created by hand on 2026-08-12.
--      Repeating the policies here means one SQL session leaves the project
--      whole; running 011 afterwards stays a no-op either way.
-- ═══════════════════════════════════════════════════════════════════════════════

-- ── 1. Bio ───────────────────────────────────────────────────────────────────
-- A public page carrying nothing but an avatar and a row of icons reads as
-- broken. 200 characters is a sentence about yourself, not a blog.

ALTER TABLE profiles ADD COLUMN IF NOT EXISTS bio TEXT;

ALTER TABLE profiles DROP CONSTRAINT IF EXISTS profiles_bio_length_check;
ALTER TABLE profiles
  ADD CONSTRAINT profiles_bio_length_check
  CHECK (bio IS NULL OR char_length(bio) <= 200);

COMMENT ON COLUMN profiles.bio IS
  'Shown on the public profile at /u/{id}. Capped at 200 characters here, in the API, and in the UI counter.';

-- ── 2. Social links ──────────────────────────────────────────────────────────
-- A table rather than a JSONB column on `profiles`: row-level security applies
-- per link, ordering is a real column, and the public endpoint can name the
-- columns it returns instead of filtering a blob.
--
-- `url` is NULL for Discord alone. A modern Discord username is not addressable
-- by URL — discord.com/users/{id} wants the numeric snowflake, which a user
-- cannot read off their own profile — so that row renders as copyable text. A
-- dead href would be the same lie the old ConnectedAccountsCard told.

CREATE TABLE IF NOT EXISTS profile_social_links (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  platform   TEXT NOT NULL CHECK (platform IN (
               'x','discord','telegram','github','linkedin','youtube','instagram',
               'tiktok','reddit','twitch','medium','substack','tradingview','custom')),
  handle     TEXT,
  label      TEXT,
  url        TEXT,
  position   SMALLINT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- A known platform can appear once per user. 'custom' is exempt so several
-- personal sites can be listed; the three-link cap lives in the service layer,
-- where it can produce a readable message instead of a constraint violation.
CREATE UNIQUE INDEX IF NOT EXISTS profile_social_links_user_platform_idx
  ON profile_social_links (user_id, platform)
  WHERE platform <> 'custom';

CREATE INDEX IF NOT EXISTS profile_social_links_user_idx
  ON profile_social_links (user_id, position);

ALTER TABLE profile_social_links ENABLE ROW LEVEL SECURITY;

-- Readable by any signed-in member: the whole point is that other people see
-- them. Not readable anonymously — /u/{id} is behind a session.
DROP POLICY IF EXISTS "Social links are readable by signed-in users" ON profile_social_links;
CREATE POLICY "Social links are readable by signed-in users"
  ON profile_social_links FOR SELECT TO authenticated
  USING (TRUE);

DROP POLICY IF EXISTS "Users insert their own social links" ON profile_social_links;
CREATE POLICY "Users insert their own social links"
  ON profile_social_links FOR INSERT TO authenticated
  WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users update their own social links" ON profile_social_links;
CREATE POLICY "Users update their own social links"
  ON profile_social_links FOR UPDATE TO authenticated
  USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users delete their own social links" ON profile_social_links;
CREATE POLICY "Users delete their own social links"
  ON profile_social_links FOR DELETE TO authenticated
  USING (auth.uid() = user_id);

COMMENT ON TABLE profile_social_links IS
  'Self-declared social handles. Nothing here is verified; do not render a verified badge against these rows.';

-- ── 3. Karma ─────────────────────────────────────────────────────────────────
-- `community_posts` has no `deleted_at`; post deletion is a hard delete, so
-- there is no tombstone to filter there. Comments are different: 007 made them
-- tombstones so that deleting a parent would not cascade its replies away. A
-- tombstoned comment should stop earning karma for text nobody can read.

CREATE OR REPLACE FUNCTION community_user_karma(uid UUID)
RETURNS TABLE (post_karma INT, comment_karma INT, total_karma INT)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  WITH p AS (
    SELECT COALESCE(SUM(score), 0)::INT AS k
      FROM community_posts WHERE user_id = uid
  ),
  c AS (
    SELECT COALESCE(SUM(score), 0)::INT AS k
      FROM community_comments WHERE user_id = uid AND deleted_at IS NULL
  )
  SELECT p.k, c.k, p.k + c.k FROM p, c;
$$;

GRANT EXECUTE ON FUNCTION community_user_karma(UUID) TO authenticated, service_role;

COMMENT ON FUNCTION community_user_karma(UUID) IS
  'Karma computed on read from community_posts.score and community_comments.score. Deliberately not denormalized onto profiles: a counter column would drift on every deletion and retracted vote.';

-- ── 4. Carried over from 011 ─────────────────────────────────────────────────
-- The profile-avatars bucket itself already exists. These are its policies,
-- which govern a direct-from-client upload path the app does not currently use
-- — uploads go through POST /api/profile/avatar with the service-role key.
-- They are repeated here so the project matches its own migrations.

DROP POLICY IF EXISTS "Profile photos are publicly readable" ON storage.objects;
CREATE POLICY "Profile photos are publicly readable"
  ON storage.objects FOR SELECT
  USING (bucket_id = 'profile-avatars');

DROP POLICY IF EXISTS "Users upload profile photos into their own folder" ON storage.objects;
CREATE POLICY "Users upload profile photos into their own folder"
  ON storage.objects FOR INSERT TO authenticated
  WITH CHECK (
    bucket_id = 'profile-avatars'
    AND (storage.foldername(name))[1] = auth.uid()::TEXT
  );

DROP POLICY IF EXISTS "Users delete their own profile photos" ON storage.objects;
CREATE POLICY "Users delete their own profile photos"
  ON storage.objects FOR DELETE TO authenticated
  USING (
    bucket_id = 'profile-avatars'
    AND (storage.foldername(name))[1] = auth.uid()::TEXT
  );
