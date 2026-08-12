-- ═══════════════════════════════════════════════════════════════════════════════
-- 011 — PROFILE: photo storage, and the email column sign-up now reads
-- Bu SQL'i Supabase Dashboard > SQL Editor'da çalıştır.
--
-- Non-destructive and re-runnable: every statement is IF NOT EXISTS, an
-- idempotent UPSERT, or an UPDATE that only fills NULLs. There are no DROPs
-- other than the CREATE-OR-REPLACE dance on storage policies.
--
-- Two things arrive here:
--
--   1. A bucket for profile photos, so the avatar stops being a URL the user
--      pastes in and becomes a file they upload.
--   2. The index and the backfill that `POST /api/auth/email/precheck` needs.
--      That endpoint answers "is this address already registered" by looking at
--      profiles.email — which the handle_new_user() trigger fills at sign-up,
--      but which an older bug in profile_service left NULL on any row the
--      backend created itself.
-- ═══════════════════════════════════════════════════════════════════════════════

-- ── 1. Storage — profile-avatars bucket ──────────────────────────────────────
-- Public: a profile photo is shown next to the name that owns it. Uploads go
-- through the backend (POST /api/profile/avatar), which sniffs the magic bytes
-- and writes under {user_id}/. The policies below matter only for a
-- direct-from-client path.
--
-- Deliberately NOT community-media: sharing one bucket would mean account
-- deletion could not clear a user's photos without also reaching into their
-- post images.

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
  'profile-avatars', 'profile-avatars', TRUE, 2097152,
  ARRAY['image/png', 'image/jpeg', 'image/webp', 'image/gif']
)
ON CONFLICT (id) DO UPDATE
  SET public = EXCLUDED.public,
      file_size_limit = EXCLUDED.file_size_limit,
      allowed_mime_types = EXCLUDED.allowed_mime_types;

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

-- ── 2. Email lookup ──────────────────────────────────────────────────────────
-- The sign-up precheck matches case-insensitively, so the index has to as well;
-- a plain index on `email` would never be used by `lower(email) = ...`.

CREATE INDEX IF NOT EXISTS profiles_email_lower_idx ON profiles (lower(email));

-- Repair rows the backend's own profile auto-create left without an address.
-- Only fills NULLs, so re-running it is a no-op and it can never overwrite an
-- address a user changed.

UPDATE profiles p
   SET email = u.email
  FROM auth.users u
 WHERE p.id = u.id
   AND p.email IS NULL;

-- ── 3. A note on user_settings.theme ─────────────────────────────────────────
-- The column stays; the application no longer offers a theme choice. Oracle-X
-- ships a single dark palette (there is one `:root` block in globals.css and no
-- `darkMode` key in the Tailwind config), so a picker wired to this column
-- would write a preference nothing reads — which is exactly what was removed.
-- Kept rather than dropped because dropping it would break any older client
-- still sending it to PUT /api/profile/settings.

COMMENT ON COLUMN user_settings.theme IS
  'Retained for compatibility. The app ships one dark palette and exposes no theme picker; do not add one on the strength of this column existing.';
