-- ═══════════════════════════════════════════════════════════════════════════════
-- 008 — COMMUNITY SEED: three example posts, one of each kind
-- Bu SQL'i Supabase Dashboard > SQL Editor'da, 007'den SONRA çalıştır.
--
-- Deliberately a separate file from 007. Seeding needs rows in `auth.users`,
-- because community_posts.user_id → profiles.id → auth.users.id, and a hosted
-- Supabase project may refuse a direct write to the auth schema depending on the
-- role running the editor. Keeping it separate means a refused seed can never
-- block the schema migration.
--
-- Everything below is idempotent: fixed UUIDs, ON CONFLICT DO NOTHING. Running
-- it twice changes nothing. To reset the examples, delete the three posts by id
-- and re-run.
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Demo authors ─────────────────────────────────────────────────────────────
-- These are real auth.users rows with an unusable password. The existing
-- handle_new_user() trigger (001_initial_schema.sql) turns each one into a
-- profiles row, reading full_name and avatar_url out of raw_user_meta_data.
--
-- Six of them rather than three: a vote is one row per user, so the size of this
-- list is the ceiling on every score the seed can produce. Three authors capped
-- the whole board at +3 and made every post look equally popular.
--
-- The four empty-string columns are not optional: GoTrue's Go structs scan them
-- as non-nullable strings and a NULL there breaks the auth admin API.

DO $$
DECLARE
  demo_authors CONSTANT JSONB := '[
    {"id": "a0000000-0000-4000-8000-000000000001",
     "email": "oracle.desk@oracle-x.demo",
     "name":  "Oracle Desk",
     "plan":  "whale"},
    {"id": "a0000000-0000-4000-8000-000000000002",
     "email": "mira.tan@oracle-x.demo",
     "name":  "Mira Tan",
     "plan":  "pro"},
    {"id": "a0000000-0000-4000-8000-000000000003",
     "email": "deniz.k@oracle-x.demo",
     "name":  "Deniz K.",
     "plan":  "free"},
    {"id": "a0000000-0000-4000-8000-000000000004",
     "email": "kaan.ergun@oracle-x.demo",
     "name":  "Kaan Ergün",
     "plan":  "pro"},
    {"id": "a0000000-0000-4000-8000-000000000005",
     "email": "selin.yildiz@oracle-x.demo",
     "name":  "Selin Yıldız",
     "plan":  "free"},
    {"id": "a0000000-0000-4000-8000-000000000006",
     "email": "burak.aydin@oracle-x.demo",
     "name":  "Burak Aydın",
     "plan":  "whale"}
  ]'::JSONB;
  author JSONB;
BEGIN
  FOR author IN SELECT * FROM jsonb_array_elements(demo_authors)
  LOOP
    INSERT INTO auth.users (
      instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
      raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
      confirmation_token, email_change, email_change_token_new, recovery_token
    ) VALUES (
      '00000000-0000-0000-0000-000000000000',
      (author ->> 'id')::UUID,
      'authenticated',
      'authenticated',
      author ->> 'email',
      crypt(gen_random_uuid()::TEXT, gen_salt('bf')),
      NOW(),
      '{"provider":"email","providers":["email"]}'::JSONB,
      jsonb_build_object('full_name', author ->> 'name'),
      NOW() - INTERVAL '30 days',
      NOW() - INTERVAL '30 days',
      '', '', '', ''
    )
    ON CONFLICT (id) DO NOTHING;

    UPDATE profiles
       SET full_name = author ->> 'name',
           subscription_plan = author ->> 'plan'
     WHERE id = (author ->> 'id')::UUID;
  END LOOP;

  RAISE NOTICE 'community seed: demo authors ready';
EXCEPTION
  WHEN OTHERS THEN
    -- A hosted project can decline writes to auth.users. Say so loudly and let
    -- the rest of the file skip itself rather than failing the migration.
    RAISE WARNING 'community seed: could not create demo authors (%). '
                  'Re-point the seed posts at an existing profile id, or run '
                  'this file with the postgres role.', SQLERRM;
END $$;

-- ── The three example posts ──────────────────────────────────────────────────

DO $$
DECLARE
  author_desk  CONSTANT UUID := 'a0000000-0000-4000-8000-000000000001';
  author_mira  CONSTANT UUID := 'a0000000-0000-4000-8000-000000000002';
  author_deniz CONSTANT UUID := 'a0000000-0000-4000-8000-000000000003';

  post_text  CONSTANT UUID := 'b0000000-0000-4000-8000-000000000001';
  post_image CONSTANT UUID := 'b0000000-0000-4000-8000-000000000002';
  post_link  CONSTANT UUID := 'b0000000-0000-4000-8000-000000000003';
BEGIN
  IF (SELECT COUNT(*) FROM profiles WHERE id IN (author_desk, author_mira, author_deniz)) < 3 THEN
    RAISE WARNING 'community seed: demo profiles missing, skipping example posts';
    RETURN;
  END IF;

  -- 1 / TEXT — exercises the markdown renderer (bold, list, inline link).
  INSERT INTO community_posts (
    id, user_id, post_kind, type, title, content, asset_symbol, created_at, updated_at
  ) VALUES (
    post_text, author_desk, 'text', 'thought',
    'Funding has been negative for three sessions while price holds',
    -- Dollar-quoted, so the markdown's own line breaks are the line breaks.
    -- Adjacent E'' literals do NOT implicitly concatenate in Postgres — only
    -- plain ones do — and "\n" soup is unreadable in a body this long anyway.
    $md$Perp funding on the majors has sat below zero since Monday, but spot is refusing to give up the range low. That combination usually means one of two things:

- **Shorts are paying to stay short** into support, which is the setup that produces the sharpest squeezes.
- Or spot demand is genuinely absorbing the sell pressure, and the derivatives crowd is offside.

The tell is open interest. If OI keeps climbing while funding stays negative, it is the first. If OI bleeds, the shorts are already covering and the move is mostly done.

I am watching the 4h close — a reclaim on rising OI is the entry, a loss of the range low on falling OI is the invalidation. The [funding dashboard](/dashboard) has the venue split.

What is everyone else seeing?$md$,
    'BTC',
    NOW() - INTERVAL '6 hours', NOW() - INTERVAL '6 hours'
  ) ON CONFLICT (id) DO NOTHING;

  -- 2 / IMAGE — the asset is committed at frontend/public/community-seed/ rather
  -- than hotlinked, so the example cannot rot. Replace it with a real uploaded
  -- URL once you have exercised POST /api/community/media.
  INSERT INTO community_posts (
    id, user_id, post_kind, type, title, content, asset_symbol, image_url,
    created_at, updated_at
  ) VALUES (
    post_image, author_mira, 'image', 'analysis',
    'ETH daily — the whole June flush has been retraced, now stalling under 1,950',
    $md$Daily ETH/USDT off OKX. Three phases on one screen:

- **May:** a slow bleed out of the 2,400s that never got a real bounce.
- **Mid-June:** the capitulation candle — biggest red volume bar on the chart, straight into 1,550.
- **July onward:** higher lows the entire way back up, and the single largest green volume bar of the range on the reclaim.

We are at 1,907 now, which is roughly the halfway mark of the whole May–June decline, and the last two weeks have been sideways chop under 1,950 on shrinking volume.

That is a decision point, not a trend. Above 1,950 with volume, the measured move points back at the 2,100 shelf. Rejection here on this kind of volume decay and the 1,850 low is the obvious retest.

Not a call, just what the chart is showing.$md$,
    'ETH',
    '/community-seed/eth-daily-range.png',
    NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days'
  ) ON CONFLICT (id) DO NOTHING;

  -- 3 / LINK — the OpenGraph columns are pre-filled so the card renders without
  -- a network fetch on first load. link_image_url is left NULL on purpose: a
  -- fabricated image URL would 404, and the card's no-image layout is worth
  -- seeing anyway.
  INSERT INTO community_posts (
    id, user_id, post_kind, type, title, content, link_url,
    link_title, link_description, link_site_name, link_fetched_at,
    created_at, updated_at
  ) VALUES (
    post_link, author_deniz, 'link', 'question',
    'How are you positioning around the next FOMC date?',
    'Calendar is here for anyone who wants the exact dates. Curious whether people are sizing down into it or treating it as noise now.',
    'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm',
    'FOMC Meeting calendars and information',
    'The Federal Open Market Committee meeting schedule, statements, minutes and projection materials.',
    'federalreserve.gov',
    NOW() - INTERVAL '1 day',
    NOW() - INTERVAL '1 day', NOW() - INTERVAL '1 day'
  ) ON CONFLICT (id) DO NOTHING;

  RAISE NOTICE 'community seed: example posts ready';
END $$;

-- ── Threads, so the comment UI has something to render ───────────────────────
-- `depth` is deliberately never written here: trg_community_comment_depth
-- derives it from parent_id, and hand-writing it would let the seed disagree
-- with the trigger. Same reason comments_count is left alone.

DO $$
DECLARE
  author_desk  CONSTANT UUID := 'a0000000-0000-4000-8000-000000000001';
  author_mira  CONSTANT UUID := 'a0000000-0000-4000-8000-000000000002';
  author_deniz CONSTANT UUID := 'a0000000-0000-4000-8000-000000000003';
  author_kaan  CONSTANT UUID := 'a0000000-0000-4000-8000-000000000004';
  author_selin CONSTANT UUID := 'a0000000-0000-4000-8000-000000000005';
  author_burak CONSTANT UUID := 'a0000000-0000-4000-8000-000000000006';

  post_text  CONSTANT UUID := 'b0000000-0000-4000-8000-000000000001';
  post_image CONSTANT UUID := 'b0000000-0000-4000-8000-000000000002';
  post_link  CONSTANT UUID := 'b0000000-0000-4000-8000-000000000003';

  -- 01-04 hang off the text post, 05-08 off the image post, 09-0B off the link.
  cmt_root  CONSTANT UUID := 'c0000000-0000-4000-8000-000000000001';
  cmt_reply CONSTANT UUID := 'c0000000-0000-4000-8000-000000000002';
  cmt_deep  CONSTANT UUID := 'c0000000-0000-4000-8000-000000000003';
  cmt_alt   CONSTANT UUID := 'c0000000-0000-4000-8000-000000000004';

  cmt_img_a CONSTANT UUID := 'c0000000-0000-4000-8000-000000000005';
  cmt_img_b CONSTANT UUID := 'c0000000-0000-4000-8000-000000000006';
  cmt_img_c CONSTANT UUID := 'c0000000-0000-4000-8000-000000000007';
  cmt_img_d CONSTANT UUID := 'c0000000-0000-4000-8000-000000000008';

  cmt_lnk_a CONSTANT UUID := 'c0000000-0000-4000-8000-000000000009';
  cmt_lnk_b CONSTANT UUID := 'c0000000-0000-4000-8000-00000000000a';
  cmt_lnk_c CONSTANT UUID := 'c0000000-0000-4000-8000-00000000000b';
BEGIN
  IF NOT EXISTS (SELECT 1 FROM community_posts WHERE id = post_text) THEN
    RAISE WARNING 'community seed: example posts missing, skipping comments';
    RETURN;
  END IF;

  -- Parents must exist before their replies, and a single multi-row INSERT does
  -- not guarantee that order for the depth trigger. Hence three statements,
  -- roots first.
  INSERT INTO community_comments (id, post_id, parent_id, user_id, content, created_at, updated_at)
  VALUES
    (cmt_root, post_text, NULL, author_mira,
     'OI is up ~8% over the same window on my screen, so I am leaning squeeze. The risk is that it is all one venue.',
     NOW() - INTERVAL '5 hours', NOW() - INTERVAL '5 hours'),

    (cmt_alt, post_text, NULL, author_kaan,
     'Third option you did not list: a basis trade unwinding. That prints negative funding with flat OI and means nothing directionally.',
     NOW() - INTERVAL '4 hours 20 minutes', NOW() - INTERVAL '4 hours 20 minutes'),

    (cmt_img_a, post_image, NULL, author_deniz,
     'The volume decay into the top of the range is the part that would keep me out. Clean markup though.',
     NOW() - INTERVAL '1 day 20 hours', NOW() - INTERVAL '1 day 20 hours'),

    (cmt_img_c, post_image, NULL, author_burak,
     'Been long since the 1,700 reclaim and I am not touching it until 1,950 either breaks or fails properly. Chop is not a signal.',
     NOW() - INTERVAL '1 day 6 hours', NOW() - INTERVAL '1 day 6 hours'),

    (cmt_lnk_a, post_link, NULL, author_selin,
     'Sizing down. Not because I have a view on the decision, but because the spreads around the release are unfair to anyone with a stop.',
     NOW() - INTERVAL '20 hours', NOW() - INTERVAL '20 hours'),

    (cmt_lnk_c, post_link, NULL, author_kaan,
     'Honestly treating it as noise now. The last four have been fully priced by the time the statement landed.',
     NOW() - INTERVAL '9 hours', NOW() - INTERVAL '9 hours')
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO community_comments (id, post_id, parent_id, user_id, content, created_at, updated_at)
  VALUES
    (cmt_reply, post_text, cmt_root, author_desk,
     'Same read. Worth splitting it by venue before sizing anything — one exchange skewing the aggregate has burned me before.',
     NOW() - INTERVAL '4 hours', NOW() - INTERVAL '4 hours'),

    (cmt_img_b, post_image, cmt_img_a, author_mira,
     'Fair. Falling volume in a range is normal though — I only start worrying if the breakout candle itself is thin.',
     NOW() - INTERVAL '1 day 14 hours', NOW() - INTERVAL '1 day 14 hours'),

    (cmt_img_d, post_image, cmt_img_c, author_selin,
     'This. The 1,850 low held twice already, so there is a real invalidation to lean on instead of guessing.',
     NOW() - INTERVAL '22 hours', NOW() - INTERVAL '22 hours'),

    (cmt_lnk_b, post_link, cmt_lnk_a, author_burak,
     'Same, and I pull resting orders 10 minutes before. Getting filled at the wick has cost me more than any actual view ever has.',
     NOW() - INTERVAL '16 hours', NOW() - INTERVAL '16 hours')
  ON CONFLICT (id) DO NOTHING;

  -- One third-level reply, to prove the nesting cap renders.
  INSERT INTO community_comments (id, post_id, parent_id, user_id, content, created_at, updated_at)
  VALUES
    (cmt_deep, post_text, cmt_reply, author_deniz,
     'Checked — Binance and Bybit are both up on the window, so it is not a single-venue artefact.',
     NOW() - INTERVAL '3 hours', NOW() - INTERVAL '3 hours')
  ON CONFLICT (id) DO NOTHING;

  RAISE NOTICE 'community seed: threads ready';
END $$;

-- ── Votes, so Hot and Top actually differ from New ───────────────────────────

DO $$
DECLARE
  author_desk  CONSTANT UUID := 'a0000000-0000-4000-8000-000000000001';
  author_mira  CONSTANT UUID := 'a0000000-0000-4000-8000-000000000002';
  author_deniz CONSTANT UUID := 'a0000000-0000-4000-8000-000000000003';
  author_kaan  CONSTANT UUID := 'a0000000-0000-4000-8000-000000000004';
  author_selin CONSTANT UUID := 'a0000000-0000-4000-8000-000000000005';
  author_burak CONSTANT UUID := 'a0000000-0000-4000-8000-000000000006';

  post_text  CONSTANT UUID := 'b0000000-0000-4000-8000-000000000001';
  post_image CONSTANT UUID := 'b0000000-0000-4000-8000-000000000002';
  post_link  CONSTANT UUID := 'b0000000-0000-4000-8000-000000000003';

  cmt_root  CONSTANT UUID := 'c0000000-0000-4000-8000-000000000001';
  cmt_reply CONSTANT UUID := 'c0000000-0000-4000-8000-000000000002';
  cmt_deep  CONSTANT UUID := 'c0000000-0000-4000-8000-000000000003';
  cmt_alt   CONSTANT UUID := 'c0000000-0000-4000-8000-000000000004';
  cmt_img_a CONSTANT UUID := 'c0000000-0000-4000-8000-000000000005';
  cmt_img_b CONSTANT UUID := 'c0000000-0000-4000-8000-000000000006';
  cmt_img_c CONSTANT UUID := 'c0000000-0000-4000-8000-000000000007';
  cmt_lnk_a CONSTANT UUID := 'c0000000-0000-4000-8000-000000000009';
  cmt_lnk_c CONSTANT UUID := 'c0000000-0000-4000-8000-00000000000b';
BEGIN
  IF NOT EXISTS (SELECT 1 FROM community_posts WHERE id = post_text) THEN
    RETURN;
  END IF;

  -- The score column is maintained by trg_community_post_score, so inserting
  -- votes is all that is needed — never write `score` directly.
  --
  -- The spread is intentional: image +5 (top), text +3, link -1 (controversial,
  -- and the only way to see how a negative score renders).
  INSERT INTO community_post_votes (post_id, user_id, value) VALUES
    (post_image, author_mira,  1),
    (post_image, author_desk,  1),
    (post_image, author_kaan,  1),
    (post_image, author_burak, 1),
    (post_image, author_selin, 1),

    (post_text,  author_desk,  1),
    (post_text,  author_mira,  1),
    (post_text,  author_deniz, 1),
    (post_text,  author_burak, 1),
    (post_text,  author_kaan, -1),

    (post_link,  author_deniz, 1),
    (post_link,  author_selin, 1),
    (post_link,  author_mira, -1),
    (post_link,  author_kaan, -1),
    (post_link,  author_burak, -1)
  ON CONFLICT (post_id, user_id) DO NOTHING;

  INSERT INTO community_comment_votes (comment_id, user_id, value) VALUES
    (cmt_root,  author_desk,  1),
    (cmt_root,  author_deniz, 1),
    (cmt_root,  author_kaan,  1),

    (cmt_alt,   author_desk,  1),
    (cmt_alt,   author_mira,  1),
    (cmt_alt,   author_burak, 1),
    (cmt_alt,   author_selin, 1),

    (cmt_reply, author_mira,  1),
    (cmt_deep,  author_mira,  1),
    (cmt_deep,  author_desk, -1),

    (cmt_img_a, author_kaan,  1),
    (cmt_img_a, author_burak, -1),
    (cmt_img_b, author_deniz, 1),
    (cmt_img_b, author_selin, 1),
    (cmt_img_c, author_mira,  1),

    (cmt_lnk_a, author_burak, 1),
    (cmt_lnk_a, author_kaan,  1),
    (cmt_lnk_c, author_selin, -1)
  ON CONFLICT (comment_id, user_id) DO NOTHING;

  RAISE NOTICE 'community seed: votes ready';
END $$;
