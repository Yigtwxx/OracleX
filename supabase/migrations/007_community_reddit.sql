-- ═══════════════════════════════════════════════════════════════════════════════
-- 007 — COMMUNITY: Reddit-style board
-- Bu SQL'i Supabase Dashboard > SQL Editor'da çalıştır.
--
-- Unlike 005_community.sql, this migration is NON-DESTRUCTIVE and re-runnable:
-- it never drops a table that holds user data. The only DROPs here are of
-- objects this file itself owns (the composite row types and the functions and
-- triggers built on them), which are recreated further down.
--
-- What it adds:
--   * post kinds (text / image / link) with cached OpenGraph metadata
--   * up/down voting with a `score`, replacing the like-only model
--   * threaded comments (parent_id + depth, capped at 4 levels) with tombstones
--   * database triggers that maintain `score` and `comments_count` atomically,
--     replacing a read-modify-write in Python that was documented as racy
--   * the indexes 005 never created
--   * RPCs that return a feed row, its author, and the *viewer's own vote* in a
--     single round-trip
--   * the `community-media` storage bucket for uploaded images
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Composite row types ──────────────────────────────────────────────────────
-- The feed row, the single-post row and the comment row are each returned by
-- more than one function. Naming the shape once keeps the three RPCs below from
-- drifting apart. CASCADE drops the dependent functions; they are recreated at
-- the bottom of this same file.

DROP TYPE IF EXISTS community_post_row CASCADE;
DROP TYPE IF EXISTS community_comment_row CASCADE;

-- ═══════════════════════════════════════════════════════════════════════════════
-- 1. POSTS
-- ═══════════════════════════════════════════════════════════════════════════════

ALTER TABLE community_posts
  ADD COLUMN IF NOT EXISTS post_kind        TEXT NOT NULL DEFAULT 'text',
  ADD COLUMN IF NOT EXISTS link_url         TEXT,
  ADD COLUMN IF NOT EXISTS link_title       TEXT,
  ADD COLUMN IF NOT EXISTS link_description TEXT,
  ADD COLUMN IF NOT EXISTS link_image_url   TEXT,
  ADD COLUMN IF NOT EXISTS link_site_name   TEXT,
  ADD COLUMN IF NOT EXISTS link_fetched_at  TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS score            INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS is_edited        BOOLEAN NOT NULL DEFAULT FALSE;

-- `post_kind` is the *shape* of the post (how it renders). `type` stays as the
-- topical flair (question / thought / analysis). They are orthogonal: an image
-- post can be an analysis, a link post can be a question.
ALTER TABLE community_posts DROP CONSTRAINT IF EXISTS community_posts_post_kind_check;
ALTER TABLE community_posts
  ADD CONSTRAINT community_posts_post_kind_check
  CHECK (post_kind IN ('text', 'image', 'link'));

-- A link post without a URL, or an image post without an image, would render as
-- an empty card. Reject them at the door rather than defending in the UI.
ALTER TABLE community_posts DROP CONSTRAINT IF EXISTS community_posts_kind_payload_check;
ALTER TABLE community_posts
  ADD CONSTRAINT community_posts_kind_payload_check
  CHECK (
    (post_kind <> 'link'  OR link_url  IS NOT NULL) AND
    (post_kind <> 'image' OR image_url IS NOT NULL)
  );

-- ═══════════════════════════════════════════════════════════════════════════════
-- 2. VOTES — community_likes becomes community_post_votes
-- ═══════════════════════════════════════════════════════════════════════════════
-- Renaming rather than recreating carries every existing like across as a +1
-- vote for free. The composite primary key (post_id, user_id) already enforces
-- one vote per user per post.

DO $$
BEGIN
  IF to_regclass('public.community_likes') IS NOT NULL
     AND to_regclass('public.community_post_votes') IS NULL THEN
    ALTER TABLE community_likes RENAME TO community_post_votes;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS community_post_votes (
  post_id    UUID REFERENCES community_posts(id) ON DELETE CASCADE,
  user_id    UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (post_id, user_id)
);

ALTER TABLE community_post_votes
  ADD COLUMN IF NOT EXISTS value SMALLINT NOT NULL DEFAULT 1;

ALTER TABLE community_post_votes DROP CONSTRAINT IF EXISTS community_post_votes_value_check;
ALTER TABLE community_post_votes
  ADD CONSTRAINT community_post_votes_value_check CHECK (value IN (-1, 1));

CREATE TABLE IF NOT EXISTS community_comment_votes (
  comment_id UUID REFERENCES community_comments(id) ON DELETE CASCADE,
  user_id    UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  value      SMALLINT NOT NULL CHECK (value IN (-1, 1)),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (comment_id, user_id)
);

-- `likes_count` is a derived counter superseded by `score`. Backfill first so
-- pre-existing likes are not silently lost, then drop the column.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'community_posts'
      AND column_name = 'likes_count'
  ) THEN
    UPDATE community_posts p
       SET score = COALESCE(
             (SELECT SUM(v.value) FROM community_post_votes v WHERE v.post_id = p.id), 0
           );
    ALTER TABLE community_posts DROP COLUMN likes_count;
  END IF;
END $$;

-- ═══════════════════════════════════════════════════════════════════════════════
-- 3. COMMENTS — threading
-- ═══════════════════════════════════════════════════════════════════════════════

ALTER TABLE community_comments
  ADD COLUMN IF NOT EXISTS parent_id  UUID REFERENCES community_comments(id) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS depth      SMALLINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS score      INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS is_edited  BOOLEAN NOT NULL DEFAULT FALSE,
  -- A tombstone rather than a hard delete: removing a comment that has replies
  -- would cascade the whole subtree away. Deleted comments render as [deleted]
  -- and keep their children readable.
  ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

ALTER TABLE community_comments DROP CONSTRAINT IF EXISTS community_comments_depth_check;
ALTER TABLE community_comments
  ADD CONSTRAINT community_comments_depth_check CHECK (depth BETWEEN 0 AND 3);

-- 005 left post_id nullable, which makes an orphaned comment representable.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM community_comments WHERE post_id IS NULL) THEN
    ALTER TABLE community_comments ALTER COLUMN post_id SET NOT NULL;
  ELSE
    RAISE NOTICE 'community_comments has rows with a NULL post_id; leaving the column nullable';
  END IF;
END $$;

-- ═══════════════════════════════════════════════════════════════════════════════
-- 4. TRIGGERS — counters the database owns
-- ═══════════════════════════════════════════════════════════════════════════════
-- Every one of these replaces a read-modify-write that used to live in
-- services/community_service.py, where two concurrent votes could each read the
-- same count and write back the same value.

CREATE OR REPLACE FUNCTION community_sync_post_score() RETURNS TRIGGER AS $$
DECLARE
  target UUID;
BEGIN
  target := COALESCE(NEW.post_id, OLD.post_id);
  UPDATE community_posts
     SET score = COALESCE(
           (SELECT SUM(v.value) FROM community_post_votes v WHERE v.post_id = target), 0
         )
   WHERE id = target;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_community_post_score ON community_post_votes;
CREATE TRIGGER trg_community_post_score
  AFTER INSERT OR UPDATE OR DELETE ON community_post_votes
  FOR EACH ROW EXECUTE FUNCTION community_sync_post_score();

CREATE OR REPLACE FUNCTION community_sync_comment_score() RETURNS TRIGGER AS $$
DECLARE
  target UUID;
BEGIN
  target := COALESCE(NEW.comment_id, OLD.comment_id);
  UPDATE community_comments
     SET score = COALESCE(
           (SELECT SUM(v.value) FROM community_comment_votes v WHERE v.comment_id = target), 0
         )
   WHERE id = target;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_community_comment_score ON community_comment_votes;
CREATE TRIGGER trg_community_comment_score
  AFTER INSERT OR UPDATE OR DELETE ON community_comment_votes
  FOR EACH ROW EXECUTE FUNCTION community_sync_comment_score();

-- comments_count tracks *visible* comments, so soft-deleting one decrements it
-- even though the row survives to hold its replies.
CREATE OR REPLACE FUNCTION community_sync_comments_count() RETURNS TRIGGER AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.deleted_at IS NULL THEN
      UPDATE community_posts SET comments_count = comments_count + 1 WHERE id = NEW.post_id;
    END IF;
  ELSIF TG_OP = 'DELETE' THEN
    IF OLD.deleted_at IS NULL THEN
      UPDATE community_posts
         SET comments_count = GREATEST(comments_count - 1, 0) WHERE id = OLD.post_id;
    END IF;
  ELSIF TG_OP = 'UPDATE' THEN
    IF OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL THEN
      UPDATE community_posts
         SET comments_count = GREATEST(comments_count - 1, 0) WHERE id = NEW.post_id;
    ELSIF OLD.deleted_at IS NOT NULL AND NEW.deleted_at IS NULL THEN
      UPDATE community_posts SET comments_count = comments_count + 1 WHERE id = NEW.post_id;
    END IF;
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_community_comments_count ON community_comments;
CREATE TRIGGER trg_community_comments_count
  AFTER INSERT OR UPDATE OR DELETE ON community_comments
  FOR EACH ROW EXECUTE FUNCTION community_sync_comments_count();

-- Depth is derived from the parent, never supplied by the client.
CREATE OR REPLACE FUNCTION community_set_comment_depth() RETURNS TRIGGER AS $$
DECLARE
  parent_depth SMALLINT;
  parent_post  UUID;
BEGIN
  IF NEW.parent_id IS NULL THEN
    NEW.depth := 0;
    RETURN NEW;
  END IF;

  SELECT c.depth, c.post_id INTO parent_depth, parent_post
    FROM community_comments c WHERE c.id = NEW.parent_id;

  IF parent_depth IS NULL THEN
    RAISE EXCEPTION 'parent comment % does not exist', NEW.parent_id
      USING ERRCODE = 'foreign_key_violation';
  END IF;

  IF parent_post <> NEW.post_id THEN
    RAISE EXCEPTION 'parent comment % belongs to a different post', NEW.parent_id
      USING ERRCODE = 'check_violation';
  END IF;

  NEW.depth := parent_depth + 1;

  IF NEW.depth > 3 THEN
    RAISE EXCEPTION 'comment nesting is limited to 4 levels'
      USING ERRCODE = 'check_violation';
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_community_comment_depth ON community_comments;
CREATE TRIGGER trg_community_comment_depth
  BEFORE INSERT ON community_comments
  FOR EACH ROW EXECUTE FUNCTION community_set_comment_depth();

-- ═══════════════════════════════════════════════════════════════════════════════
-- 5. INDEXES — 005 created none
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE INDEX IF NOT EXISTS idx_community_posts_created    ON community_posts (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_community_posts_score      ON community_posts (score DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_community_posts_type       ON community_posts (type);
CREATE INDEX IF NOT EXISTS idx_community_posts_symbol     ON community_posts (asset_symbol) WHERE asset_symbol IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_community_posts_user       ON community_posts (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_community_comments_post    ON community_comments (post_id, created_at);
CREATE INDEX IF NOT EXISTS idx_community_comments_parent  ON community_comments (parent_id);
CREATE INDEX IF NOT EXISTS idx_community_post_votes_user  ON community_post_votes (user_id);
CREATE INDEX IF NOT EXISTS idx_community_cmt_votes_user   ON community_comment_votes (user_id);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 6. RLS
-- ═══════════════════════════════════════════════════════════════════════════════
-- The backend talks to Postgres with the service role and bypasses all of this
-- (see backend/config.py — SUPABASE_SERVICE_ROLE_KEY), so authorization is
-- enforced in the application layer. These policies exist so that a future
-- direct-from-client path is not wide open by default.

ALTER TABLE community_post_votes    ENABLE ROW LEVEL SECURITY;
ALTER TABLE community_comment_votes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public likes are viewable by everyone" ON community_post_votes;
DROP POLICY IF EXISTS "Users can insert their own likes"      ON community_post_votes;
DROP POLICY IF EXISTS "Users can delete own likes"            ON community_post_votes;

DROP POLICY IF EXISTS "Post votes are viewable by everyone" ON community_post_votes;
CREATE POLICY "Post votes are viewable by everyone"
  ON community_post_votes FOR SELECT USING (true);

DROP POLICY IF EXISTS "Users manage own post votes" ON community_post_votes;
CREATE POLICY "Users manage own post votes"
  ON community_post_votes FOR ALL
  USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Comment votes are viewable by everyone" ON community_comment_votes;
CREATE POLICY "Comment votes are viewable by everyone"
  ON community_comment_votes FOR SELECT USING (true);

DROP POLICY IF EXISTS "Users manage own comment votes" ON community_comment_votes;
CREATE POLICY "Users manage own comment votes"
  ON community_comment_votes FOR ALL
  USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- 005 gave comments insert/delete but no update; editing needs it.
DROP POLICY IF EXISTS "Users can update own comments" ON community_comments;
CREATE POLICY "Users can update own comments"
  ON community_comments FOR UPDATE USING (auth.uid() = user_id);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 7. ROW TYPES + FEED RPCs
-- ═══════════════════════════════════════════════════════════════════════════════
-- Why functions and not a view: the feed has to carry the *viewer's* own vote,
-- which is a per-request parameter, and PostgREST's foreign-key embedding
-- (profiles!community_posts_user_id_fkey(...)) does not reliably resolve through
-- views. One RPC returns the post, its author and my_vote in a single query.

CREATE TYPE community_post_row AS (
  id                UUID,
  user_id           UUID,
  title             TEXT,
  content           TEXT,
  type              TEXT,
  post_kind         TEXT,
  asset_symbol      TEXT,
  image_url         TEXT,
  link_url          TEXT,
  link_title        TEXT,
  link_description  TEXT,
  link_image_url    TEXT,
  link_site_name    TEXT,
  score             INTEGER,
  comments_count    INTEGER,
  is_edited         BOOLEAN,
  created_at        TIMESTAMPTZ,
  updated_at        TIMESTAMPTZ,
  author_name       TEXT,
  author_avatar_url TEXT,
  author_plan       TEXT,
  my_vote           SMALLINT
);

CREATE TYPE community_comment_row AS (
  id                UUID,
  post_id           UUID,
  parent_id         UUID,
  user_id           UUID,
  content           TEXT,
  score             INTEGER,
  depth             SMALLINT,
  is_edited         BOOLEAN,
  deleted_at        TIMESTAMPTZ,
  created_at        TIMESTAMPTZ,
  updated_at        TIMESTAMPTZ,
  author_name       TEXT,
  author_avatar_url TEXT,
  author_plan       TEXT,
  my_vote           SMALLINT
);

-- Hot ranking is Reddit's: the log of the score (so the 10th upvote matters far
-- less than the 1st) plus an age term, which lets a fresh post outrank a stale
-- one it cannot yet match on votes. 45000 seconds ≈ 12.5h is the half-life.
--
-- The ORDER BY computes it per row rather than reading a stored column. At this
-- board's size a sort over community_posts costs nothing; past ~100k posts,
-- promote it to a `hot_rank` column maintained by trg_community_post_score.
CREATE OR REPLACE FUNCTION get_community_feed(
  p_sort    TEXT    DEFAULT 'hot',
  p_type    TEXT    DEFAULT NULL,
  p_symbol  TEXT    DEFAULT NULL,
  p_author  UUID    DEFAULT NULL,
  p_post_id UUID    DEFAULT NULL,
  p_viewer  UUID    DEFAULT NULL,
  p_limit   INTEGER DEFAULT 20,
  p_offset  INTEGER DEFAULT 0
) RETURNS SETOF community_post_row
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT
    p.id, p.user_id, p.title, p.content, p.type, p.post_kind, p.asset_symbol,
    p.image_url, p.link_url, p.link_title, p.link_description, p.link_image_url,
    p.link_site_name, p.score, p.comments_count, p.is_edited,
    p.created_at, p.updated_at,
    pr.full_name, pr.avatar_url, pr.subscription_plan,
    COALESCE(v.value, 0::SMALLINT)
  FROM community_posts p
  LEFT JOIN profiles pr ON pr.id = p.user_id
  LEFT JOIN community_post_votes v
         ON v.post_id = p.id AND p_viewer IS NOT NULL AND v.user_id = p_viewer
  WHERE (p_post_id IS NULL OR p.id = p_post_id)
    AND (p_type   IS NULL OR p_type = 'all' OR p.type = p_type)
    AND (p_symbol IS NULL OR p.asset_symbol = UPPER(p_symbol))
    AND (p_author IS NULL OR p.user_id = p_author)
  ORDER BY
    CASE WHEN p_sort = 'hot' THEN
      LOG(GREATEST(ABS(p.score), 1)::NUMERIC) * SIGN(p.score)
        + EXTRACT(EPOCH FROM p.created_at) / 45000.0
    END DESC NULLS LAST,
    CASE WHEN p_sort = 'top' THEN p.score END DESC NULLS LAST,
    p.created_at DESC
  LIMIT GREATEST(LEAST(p_limit, 100), 1)
  OFFSET GREATEST(p_offset, 0);
$$;

CREATE OR REPLACE FUNCTION get_community_post(
  p_post_id UUID,
  p_viewer  UUID DEFAULT NULL
) RETURNS SETOF community_post_row
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT * FROM get_community_feed(
    p_sort => 'new', p_post_id => p_post_id, p_viewer => p_viewer, p_limit => 1
  );
$$;

-- Returned flat and ordered; the backend assembles the tree. Depth is capped at
-- 4 levels, so a recursive CTE would buy nothing over a single indexed scan.
CREATE OR REPLACE FUNCTION get_community_comments(
  p_post_id UUID,
  p_viewer  UUID DEFAULT NULL
) RETURNS SETOF community_comment_row
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT
    c.id, c.post_id, c.parent_id, c.user_id,
    -- The author of a tombstoned comment is not disclosed either.
    CASE WHEN c.deleted_at IS NULL THEN c.content ELSE NULL END,
    c.score, c.depth, c.is_edited, c.deleted_at, c.created_at, c.updated_at,
    CASE WHEN c.deleted_at IS NULL THEN pr.full_name  ELSE NULL END,
    CASE WHEN c.deleted_at IS NULL THEN pr.avatar_url ELSE NULL END,
    CASE WHEN c.deleted_at IS NULL THEN pr.subscription_plan ELSE NULL END,
    COALESCE(v.value, 0::SMALLINT)
  FROM community_comments c
  LEFT JOIN profiles pr ON pr.id = c.user_id
  LEFT JOIN community_comment_votes v
         ON v.comment_id = c.id AND p_viewer IS NOT NULL AND v.user_id = p_viewer
  WHERE c.post_id = p_post_id
  ORDER BY c.depth, c.score DESC, c.created_at;
$$;

-- Sidebar: which tickers the board is actually talking about.
CREATE OR REPLACE FUNCTION get_community_trending_assets(
  p_days  INTEGER DEFAULT 7,
  p_limit INTEGER DEFAULT 8
) RETURNS TABLE (asset_symbol TEXT, post_count BIGINT, total_score BIGINT)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT p.asset_symbol, COUNT(*)::BIGINT, COALESCE(SUM(p.score), 0)::BIGINT
  FROM community_posts p
  WHERE p.asset_symbol IS NOT NULL
    AND p.created_at > NOW() - (GREATEST(p_days, 1) || ' days')::INTERVAL
  GROUP BY p.asset_symbol
  ORDER BY COUNT(*) DESC, COALESCE(SUM(p.score), 0) DESC
  LIMIT GREATEST(LEAST(p_limit, 25), 1);
$$;

CREATE OR REPLACE FUNCTION get_community_stats()
RETURNS TABLE (total_posts BIGINT, posts_today BIGINT, contributors BIGINT)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT
    COUNT(*)::BIGINT,
    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours')::BIGINT,
    COUNT(DISTINCT user_id)::BIGINT
  FROM community_posts;
$$;

GRANT EXECUTE ON FUNCTION get_community_feed(TEXT, TEXT, TEXT, UUID, UUID, UUID, INTEGER, INTEGER)
  TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION get_community_post(UUID, UUID)
  TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION get_community_comments(UUID, UUID)
  TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION get_community_trending_assets(INTEGER, INTEGER)
  TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION get_community_stats()
  TO anon, authenticated, service_role;

-- ═══════════════════════════════════════════════════════════════════════════════
-- 8. STORAGE — community-media bucket
-- ═══════════════════════════════════════════════════════════════════════════════
-- Public bucket: post images are world-readable, same as the posts themselves.
-- Uploads go through the backend (POST /api/community/media), which validates
-- the file and writes under {user_id}/. The policies below matter only for a
-- direct-from-client upload path.

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
  'community-media', 'community-media', TRUE, 5242880,
  ARRAY['image/png', 'image/jpeg', 'image/webp', 'image/gif']
)
ON CONFLICT (id) DO UPDATE
  SET public = EXCLUDED.public,
      file_size_limit = EXCLUDED.file_size_limit,
      allowed_mime_types = EXCLUDED.allowed_mime_types;

DROP POLICY IF EXISTS "Community media is publicly readable" ON storage.objects;
CREATE POLICY "Community media is publicly readable"
  ON storage.objects FOR SELECT
  USING (bucket_id = 'community-media');

DROP POLICY IF EXISTS "Users upload community media into their own folder" ON storage.objects;
CREATE POLICY "Users upload community media into their own folder"
  ON storage.objects FOR INSERT TO authenticated
  WITH CHECK (
    bucket_id = 'community-media'
    AND (storage.foldername(name))[1] = auth.uid()::TEXT
  );

DROP POLICY IF EXISTS "Users delete their own community media" ON storage.objects;
CREATE POLICY "Users delete their own community media"
  ON storage.objects FOR DELETE TO authenticated
  USING (
    bucket_id = 'community-media'
    AND (storage.foldername(name))[1] = auth.uid()::TEXT
  );
