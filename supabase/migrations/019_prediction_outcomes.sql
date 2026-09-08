-- ═══════════════════════════════════════════════════════════════════════════════
-- ORACLE-X TRACK RECORD
--
-- What the terminal said would happen, and what the price actually did.
--
-- The pieces for this existed and were never joined. `rag_outcomes` could
-- measure an event's aftermath over six horizons, `news_analysis_store` kept
-- every verdict on disk with an `outcome` field waiting to be filled, and its
-- docstring described the job that would fill it. That job was never written:
-- `record_outcome()` and `pending_outcomes()` had no callers, and every stored
-- analysis carried a null outcome from the day it was made. A terminal that
-- publishes a directional call and never checks it is asking to be believed on
-- its tone.
--
-- ─── WHY TWO TABLES ───────────────────────────────────────────────────────────
--
-- A prediction's 1-day horizon can be measured tomorrow; its 365-day horizon
-- cannot be measured for a year. Held in one row that would mean rewriting the
-- same record five times as the horizons arrive, and a track record you can
-- rewrite is not evidence of anything. Splitting the grain — the verdict here,
-- one row per (verdict × horizon) next door — turns each late measurement into
-- an ordinary insert, which is what lets both tables be append-only.
--
-- Nothing in the application issues UPDATE or DELETE against either table.
-- ═══════════════════════════════════════════════════════════════════════════════

-- ─────────────────────────────────────────────────────────────────────────────
-- THE VERDICT
--
-- One row per analysis, ingested from `news_analysis_store` by the scoring job
-- rather than written on the analysis hot path. Two reasons: a database
-- round-trip inside `_persist` would be paid on every reply, for a figure
-- nobody reads in real time; and ingesting from the store means the analyses
-- already sitting on disk are picked up on the first pass instead of the
-- record starting empty.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS predictions (
    id                  BIGSERIAL PRIMARY KEY,

    news_id             TEXT NOT NULL,
    -- A prompt edit retires every cached analysis and starts a new pipeline.
    -- Keeping the version on the row is what stops two pipelines being averaged
    -- into one number that describes neither.
    pipeline_version    TEXT NOT NULL,

    symbol              TEXT,
    asset_type          TEXT NOT NULL DEFAULT 'crypto',

    -- bullish | bearish | neutral. The claim being scored.
    predicted_direction TEXT NOT NULL,
    confidence          DOUBLE PRECISION,
    materiality         TEXT,
    model               TEXT,
    -- 'keyword-fallback' when no model was reachable and the verdict came from
    -- a word count over the headline. Kept because it must be excluded from the
    -- headline figure: it is not a thing the model said.
    verdict_source      TEXT,

    -- The horizons are measured from here — the moment the verdict existed.
    --
    -- Measuring from `published_at` instead would credit the model for whatever
    -- the price did between the headline landing and the analysis running,
    -- which is a move no reader could have acted on. `published_at` is stored
    -- beside it so that lag stays visible rather than assumed to be zero.
    predicted_at        TIMESTAMP WITH TIME ZONE NOT NULL,
    published_at        TIMESTAMP WITH TIME ZONE,

    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- The ingest is idempotent on this pair: re-running the job re-reads the
    -- same store and must not duplicate a verdict.
    CONSTRAINT predictions_news_pipeline_key UNIQUE (news_id, pipeline_version)
);

-- The scoring job's own scan: which verdicts are old enough to have a reachable
-- horizon. Every read of this table is time-ordered.
CREATE INDEX IF NOT EXISTS idx_predictions_predicted_at
    ON predictions (predicted_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- THE MEASUREMENT
--
-- One row per (verdict × horizon), written once, when that horizon first
-- becomes measurable.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS prediction_outcomes (
    id                BIGSERIAL PRIMARY KEY,

    -- CASCADE rather than SET NULL, the opposite of `ai_usage`: an outcome
    -- whose verdict is gone is not a measurement of anything, where a usage row
    -- whose user is gone is still spend the install incurred.
    prediction_id     BIGINT NOT NULL REFERENCES predictions(id) ON DELETE CASCADE,
    horizon_days      INTEGER NOT NULL,

    -- 'measured' | 'unmeasurable'.
    --
    -- The second is what stops a symbol the venues do not carry from being
    -- retried on every pass forever. Past the give-up window the horizon is
    -- closed with nulls and counted as unmeasurable — a number the page
    -- reports, rather than a silent gap in the denominator.
    status            TEXT NOT NULL DEFAULT 'measured',

    -- Null on an unmeasurable row. Never zero: a horizon that could not be read
    -- is a different fact from one that did not move, and averaging the two
    -- together is how a flat market and a missing venue come to look alike.
    price_change_pct  DOUBLE PRECISION,
    measured_direction TEXT,
    -- Null when the direction could not be established, so an unmeasurable
    -- horizon never counts as a miss.
    hit               BOOLEAN,

    -- Where it travelled, not just where it settled. An endpoint alone hides
    -- the call that was right at ninety days having been 40% underwater at
    -- thirty.
    max_drawdown_pct  DOUBLE PRECISION,
    max_runup_pct     DOUBLE PRECISION,

    measured_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    CONSTRAINT prediction_outcomes_prediction_horizon_key
        UNIQUE (prediction_id, horizon_days)
);

-- The summary reads every scored row and groups in Python; the join back to the
-- verdict is the only access path that is not a full scan.
CREATE INDEX IF NOT EXISTS idx_prediction_outcomes_prediction
    ON prediction_outcomes (prediction_id);

-- "What has been scored lately", for the page's recent-calls list.
CREATE INDEX IF NOT EXISTS idx_prediction_outcomes_measured_at
    ON prediction_outcomes (measured_at DESC);

-- ═══════════════════════════════════════════════════════════════════════════════
-- ROW LEVEL SECURITY
--
-- Defence in depth: the backend uses the service-role key and bypasses these.
--
-- Unlike every other table here, the SELECT policy is open rather than scoped to
-- an owner. That is the point of the feature — a track record readable only by
-- the person who kept it is not a track record — and it is why there is
-- deliberately no INSERT, UPDATE or DELETE policy for anyone: the rows are the
-- evidence, and a client that could write them could write itself a record.
-- ═══════════════════════════════════════════════════════════════════════════════

ALTER TABLE predictions ENABLE ROW LEVEL SECURITY;
ALTER TABLE prediction_outcomes ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    CREATE POLICY "Predictions are public"
        ON predictions FOR SELECT USING (TRUE);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE POLICY "Prediction outcomes are public"
        ON prediction_outcomes FOR SELECT USING (TRUE);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
