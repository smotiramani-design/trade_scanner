-- schema.sql — Trade Scanner database schema (Supabase / Postgres)
--
-- Idempotent migration: safe to run repeatedly. Creates the tables on a fresh
-- database, and ADD-COLUMN-IF-NOT-EXISTS upgrades an existing one without
-- touching your data. utils/db_writer.py runs this automatically on first write.
--
-- Design: ONE set of tables for all time (not a table per day). Postgres handles
-- this easily for years. You navigate by the Eastern-time columns below.
--
--   scans  — one row per scanner run
--   picks  — the top bullish/bearish conviction picks for each scan
--   trades — trade decisions at the 10 AM / 12 PM / 2 PM scan runs
--
-- Schedule (ET, Mon–Fri, top of hour):
--   10:00–15:00  hourly scan
--   10:00, 12:00, 14:00  scan + trade
--   16:00  Fib target hit validation (fib_hit on picks)
-- Eastern-time columns make browsing intuitive (run_ts itself is stored in UTC):
--   trade_date  the ET calendar day      (e.g. 2026-06-13)   ← filter by day
--   et_time     the ET wall-clock HH:MM   (e.g. 09:35)        ← see the hour
--   et_hour     the ET hour as an int     (e.g. 9)            ← filter/group by hour
--
-- Easiest way to browse: open the view  v_scan_picks  in the Table Editor,
-- then sort by trade_date ↓, et_hour, conviction ↓.

-- ── Tables (fresh installs) ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scans (
    id          BIGSERIAL PRIMARY KEY,
    run_ts      TIMESTAMPTZ NOT NULL DEFAULT now(),  -- exact run time (UTC)
    trade_date  DATE,                                -- ET calendar day
    et_time     TEXT,                                -- ET HH:MM
    et_hour     INT,                                 -- ET hour (0–23)
    session     TEXT,                                -- premarket / open / afterhours / closed
    universe    TEXT,
    mode        TEXT,                                -- Hourly / Daily
    n_results   INT,
    trade_run   BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS picks (
    id             BIGSERIAL PRIMARY KEY,
    scan_id        BIGINT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    trade_date     DATE,        -- denormalized from scans for easy filtering
    et_time        TEXT,        -- denormalized from scans
    ticker         TEXT NOT NULL,
    company        TEXT,
    sector         TEXT,
    direction      TEXT,        -- bull / bear
    rank           INT,         -- 1 = top pick within its direction
    price          NUMERIC,
    chg_pct        NUMERIC,
    net_score      INT,
    conviction     NUMERIC,     -- conviction % (0–100)
    weighted_score NUMERIC,     -- raw weighted conviction score
    grade          TEXT,        -- A+ / A / B / C / D
    verdict        TEXT,
    analysis       TEXT,        -- the full conviction commentary paragraph
    key_signals    JSONB,       -- ["Candle pattern (Bullish engulfing)", ...]
    conflicting    JSONB,       -- ["stochastics vs candle", ...]
    fib_target     NUMERIC,     -- primary Fib take-profit (hit-validated)
    fib_label      TEXT,
    fib_entry      NUMERIC,     -- Fib pullback/bounce entry
    fib_stop       NUMERIC,     -- Fib invalidation stop
    fib_t1         NUMERIC,     -- first extension target
    fib_t2         NUMERIC,     -- second extension target
    fib_hit        BOOLEAN,     -- set at 4 PM: did price hit target within 1 hr?
    fib_window_high NUMERIC,    -- high in the validation window (internal)
    fib_window_low  NUMERIC,    -- low in the validation window (internal)
    fib_validated_at TIMESTAMPTZ,
    mtf_aligned    BOOLEAN,     -- multi-timeframe confirmation
    earnings_soon  BOOLEAN,     -- earnings within 2 days
    atr_stop       NUMERIC,
    signals        JSONB,       -- {"Candle pattern": {"bias": "bull", "label": "..."}, ...}
    phit           NUMERIC      -- model P(fib target hit), 0–1; drives pick ranking
);

CREATE TABLE IF NOT EXISTS trades (
    id           BIGSERIAL PRIMARY KEY,
    scan_id      BIGINT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    ts           TIMESTAMPTZ NOT NULL DEFAULT now(),
    trade_date   DATE,
    et_time      TEXT,
    ticker       TEXT NOT NULL,
    action       TEXT,          -- buy / sell / skip
    reason       TEXT,
    qty          NUMERIC,
    entry_price  NUMERIC,
    stop_loss    NUMERIC,
    take_profit  NUMERIC,
    size_usd     NUMERIC,
    order_id     TEXT,          -- Alpaca order id when executed
    status       TEXT,          -- executed / skip / dry_run / failed
    dry_run      BOOLEAN NOT NULL DEFAULT FALSE
);

-- ── Upgrade existing installs (no-ops on fresh installs) ──────────────────────
ALTER TABLE scans  ADD COLUMN IF NOT EXISTS trade_date DATE;
ALTER TABLE scans  ADD COLUMN IF NOT EXISTS et_time    TEXT;
ALTER TABLE scans  ADD COLUMN IF NOT EXISTS et_hour    INT;
ALTER TABLE picks  ADD COLUMN IF NOT EXISTS trade_date DATE;
ALTER TABLE picks  ADD COLUMN IF NOT EXISTS et_time    TEXT;
ALTER TABLE picks  ADD COLUMN IF NOT EXISTS fib_hit           BOOLEAN;
ALTER TABLE picks  ADD COLUMN IF NOT EXISTS fib_window_high   NUMERIC;
ALTER TABLE picks  ADD COLUMN IF NOT EXISTS fib_window_low    NUMERIC;
ALTER TABLE picks  ADD COLUMN IF NOT EXISTS fib_validated_at  TIMESTAMPTZ;
ALTER TABLE picks  ADD COLUMN IF NOT EXISTS fib_entry         NUMERIC;
ALTER TABLE picks  ADD COLUMN IF NOT EXISTS fib_stop          NUMERIC;
ALTER TABLE picks  ADD COLUMN IF NOT EXISTS fib_t1            NUMERIC;
ALTER TABLE picks  ADD COLUMN IF NOT EXISTS fib_t2            NUMERIC;
ALTER TABLE picks  ADD COLUMN IF NOT EXISTS phit              NUMERIC;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS trade_date DATE;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS et_time    TEXT;

-- ── Indexes for fast browsing by day / hour and most-recent-first ─────────────
CREATE INDEX IF NOT EXISTS idx_scans_run_ts     ON scans (run_ts DESC);
CREATE INDEX IF NOT EXISTS idx_scans_day_hour   ON scans (trade_date DESC, et_hour);
CREATE INDEX IF NOT EXISTS idx_picks_scan_id    ON picks (scan_id);
CREATE INDEX IF NOT EXISTS idx_picks_day        ON picks (trade_date DESC, direction, rank);
CREATE INDEX IF NOT EXISTS idx_trades_scan_id   ON trades (scan_id);
CREATE INDEX IF NOT EXISTS idx_trades_day       ON trades (trade_date DESC);

-- ── Flat browsing view: one row per pick, joined to its scan ──────────────────
-- DROP + CREATE (not OR REPLACE) so new columns can be added mid-list on upgrades.
DROP VIEW IF EXISTS v_today_picks;
DROP VIEW IF EXISTS v_scan_picks;

CREATE VIEW v_scan_picks AS
SELECT
    s.trade_date,
    s.et_time,
    s.et_hour,
    s.session,
    p.direction,
    p.rank,
    p.ticker,
    p.company,
    p.conviction,
    p.grade,
    p.net_score,
    p.price,
    p.chg_pct,
    p.fib_target,
    p.fib_label,
    p.fib_entry,
    p.fib_stop,
    p.fib_t1,
    p.fib_t2,
    p.fib_hit,
    p.fib_window_high,
    p.fib_window_low,
    p.mtf_aligned,
    p.earnings_soon,
    p.verdict,
    p.analysis,
    p.key_signals,
    p.conflicting,
    p.signals,
    s.universe,
    s.trade_run,
    s.run_ts,
    p.scan_id
FROM picks p
JOIN scans s ON s.id = p.scan_id
ORDER BY s.run_ts DESC, p.direction, p.rank;

-- ── Convenience view: just today's picks (ET) ─────────────────────────────────
CREATE VIEW v_today_picks AS
SELECT * FROM v_scan_picks
WHERE trade_date = (now() AT TIME ZONE 'America/New_York')::date;

-- ── Dashboard read access (Supabase publishable / anon key) ───────────────────
-- Run in Supabase SQL Editor so the Vercel dashboard can read scan data.
GRANT USAGE ON SCHEMA public TO anon, authenticated;

GRANT SELECT ON scans, picks, trades TO anon, authenticated;
GRANT SELECT ON v_scan_picks, v_today_picks TO anon, authenticated;

ALTER TABLE scans  ENABLE ROW LEVEL SECURITY;
ALTER TABLE picks  ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "anon_read_scans"  ON scans;
DROP POLICY IF EXISTS "anon_read_picks"  ON picks;
DROP POLICY IF EXISTS "anon_read_trades" ON trades;
CREATE POLICY "anon_read_scans"  ON scans  FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read_picks"  ON picks  FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read_trades" ON trades FOR SELECT TO anon USING (true);

-- ── Pre-Market Momentum Screener (daily 9:15 AM ET) ─────────────────────────
CREATE TABLE IF NOT EXISTS momentum_scans (
    id          BIGSERIAL PRIMARY KEY,
    run_ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
    trade_date  DATE,
    et_time     TEXT,
    et_hour     INT,
    session     TEXT,
    universe    TEXT,
    n_results   INT,
    n_trade     INT,
    n_watch     INT,
    n_skip      INT
);

CREATE TABLE IF NOT EXISTS momentum_picks (
    id              BIGSERIAL PRIMARY KEY,
    scan_id         BIGINT NOT NULL REFERENCES momentum_scans(id) ON DELETE CASCADE,
    trade_date      DATE,
    et_time         TEXT,
    ticker          TEXT NOT NULL,
    company         TEXT,
    sector          TEXT,
    tier            TEXT,           -- TRADE / WATCH / SKIP
    rank            INT,             -- 1-based within TRADE tier
    score           INT,             -- 0–5 signal score
    conviction      NUMERIC,         -- 0–88 sub-rank (TRADE tier only)
    session         TEXT,
    pm_change_pct   NUMERIC,
    pm_volume       BIGINT,
    pm_price        NUMERIC,
    prev_close      NUMERIC,
    gap_pct         NUMERIC,
    l1_catalyst     TEXT,
    l2_volume       TEXT,
    l3_price        TEXT,
    l4_rs           TEXT,
    l5_options      TEXT,
    data_sources    TEXT,
    raw_signals     JSONB
);

CREATE INDEX IF NOT EXISTS idx_momentum_scans_run_ts   ON momentum_scans (run_ts DESC);
CREATE INDEX IF NOT EXISTS idx_momentum_scans_day      ON momentum_scans (trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_momentum_picks_scan_id  ON momentum_picks (scan_id);
CREATE INDEX IF NOT EXISTS idx_momentum_picks_day      ON momentum_picks (trade_date DESC, tier, rank);

-- ── Daily scanner upgrade (conviction + Fibonacci model, top 10 long/short) ───
-- The daily scan now reuses the intraday 10-signal + sentiment + Fibonacci engine
-- on daily bars. These columns extend the original pre-market momentum tables so
-- the same tables carry: direction (long/short), conviction/grade, the full Fib
-- plan, the whole-day (9:15→4 PM) target, and the 4 PM target-hit result.
ALTER TABLE momentum_scans ADD COLUMN IF NOT EXISTS mode    TEXT;   -- 'Daily'
ALTER TABLE momentum_scans ADD COLUMN IF NOT EXISTS n_long  INT;
ALTER TABLE momentum_scans ADD COLUMN IF NOT EXISTS n_short INT;

ALTER TABLE momentum_picks ADD COLUMN IF NOT EXISTS direction        TEXT;      -- 'bull' | 'bear'
ALTER TABLE momentum_picks ADD COLUMN IF NOT EXISTS net_score        INT;       -- raw −10…+10
ALTER TABLE momentum_picks ADD COLUMN IF NOT EXISTS grade            TEXT;      -- A+ / A / B / C / D
ALTER TABLE momentum_picks ADD COLUMN IF NOT EXISTS price            NUMERIC;   -- price at scan time (9:15)
ALTER TABLE momentum_picks ADD COLUMN IF NOT EXISTS chg_pct          NUMERIC;   -- session change %
ALTER TABLE momentum_picks ADD COLUMN IF NOT EXISTS analysis         TEXT;      -- conviction commentary
ALTER TABLE momentum_picks ADD COLUMN IF NOT EXISTS key_signals      JSONB;
ALTER TABLE momentum_picks ADD COLUMN IF NOT EXISTS signals          JSONB;
ALTER TABLE momentum_picks ADD COLUMN IF NOT EXISTS phit             NUMERIC;   -- model P(target hit), 0–1
ALTER TABLE momentum_picks ADD COLUMN IF NOT EXISTS fib_direction    TEXT;
ALTER TABLE momentum_picks ADD COLUMN IF NOT EXISTS fib_entry        NUMERIC;
ALTER TABLE momentum_picks ADD COLUMN IF NOT EXISTS fib_stop         NUMERIC;
ALTER TABLE momentum_picks ADD COLUMN IF NOT EXISTS fib_t1           NUMERIC;
ALTER TABLE momentum_picks ADD COLUMN IF NOT EXISTS fib_t2           NUMERIC;
ALTER TABLE momentum_picks ADD COLUMN IF NOT EXISTS fib_t3           NUMERIC;
ALTER TABLE momentum_picks ADD COLUMN IF NOT EXISTS day_target       NUMERIC;   -- whole-day (9:15→4 PM) Fib target
ALTER TABLE momentum_picks ADD COLUMN IF NOT EXISTS day_target_label TEXT;
ALTER TABLE momentum_picks ADD COLUMN IF NOT EXISTS target_hit       BOOLEAN;   -- set at 4 PM
ALTER TABLE momentum_picks ADD COLUMN IF NOT EXISTS day_high         NUMERIC;   -- session high (9:15→4 PM)
ALTER TABLE momentum_picks ADD COLUMN IF NOT EXISTS day_low          NUMERIC;   -- session low  (9:15→4 PM)
ALTER TABLE momentum_picks ADD COLUMN IF NOT EXISTS validated_at     TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_momentum_picks_dir ON momentum_picks (trade_date DESC, direction, rank);

DROP VIEW IF EXISTS v_today_momentum_picks;
DROP VIEW IF EXISTS v_momentum_picks;
DROP VIEW IF EXISTS v_momentum_hit_stats;

CREATE VIEW v_momentum_picks AS
SELECT
    s.trade_date,
    s.et_time,
    s.et_hour,
    s.session,
    s.universe,
    s.mode,
    s.run_ts,
    p.scan_id,
    p.ticker,
    p.company,
    p.sector,
    p.tier,
    p.direction,
    p.rank,
    p.score,
    p.net_score,
    p.conviction,
    p.grade,
    p.price,
    p.chg_pct,
    p.pm_change_pct,
    p.pm_volume,
    p.pm_price,
    p.prev_close,
    p.gap_pct,
    p.analysis,
    p.key_signals,
    p.signals,
    p.phit,
    p.fib_direction,
    p.fib_entry,
    p.fib_stop,
    p.fib_t1,
    p.fib_t2,
    p.fib_t3,
    p.day_target,
    p.day_target_label,
    p.target_hit,
    p.day_high,
    p.day_low,
    p.validated_at,
    p.l1_catalyst,
    p.l2_volume,
    p.l3_price,
    p.l4_rs,
    p.l5_options,
    p.data_sources
FROM momentum_picks p
JOIN momentum_scans s ON s.id = p.scan_id
ORDER BY s.run_ts DESC, p.direction, p.rank NULLS LAST, p.conviction DESC NULLS LAST;

CREATE VIEW v_today_momentum_picks AS
SELECT * FROM v_momentum_picks
WHERE trade_date = (now() AT TIME ZONE 'America/New_York')::date;

-- Per-day hit-rate stats for the whole-day Fib target (populated at 4 PM).
CREATE VIEW v_momentum_hit_stats AS
SELECT
    trade_date,
    count(*)                                                      AS n_picks,
    count(*) FILTER (WHERE direction = 'bull')                    AS n_long,
    count(*) FILTER (WHERE direction = 'bear')                    AS n_short,
    count(*) FILTER (WHERE target_hit IS NOT NULL)                AS validated,
    count(*) FILTER (WHERE target_hit)                            AS hits,
    count(*) FILTER (WHERE target_hit = false)                    AS misses,
    count(*) FILTER (WHERE direction = 'bull' AND target_hit IS NOT NULL) AS long_validated,
    count(*) FILTER (WHERE direction = 'bull' AND target_hit)             AS long_hits,
    count(*) FILTER (WHERE direction = 'bear' AND target_hit IS NOT NULL) AS short_validated,
    count(*) FILTER (WHERE direction = 'bear' AND target_hit)             AS short_hits
FROM momentum_picks
GROUP BY trade_date
ORDER BY trade_date DESC;

GRANT SELECT ON momentum_scans, momentum_picks TO anon, authenticated;
GRANT SELECT ON v_momentum_picks, v_today_momentum_picks, v_momentum_hit_stats TO anon, authenticated;

ALTER TABLE momentum_scans ENABLE ROW LEVEL SECURITY;
ALTER TABLE momentum_picks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "anon_read_momentum_scans" ON momentum_scans;
DROP POLICY IF EXISTS "anon_read_momentum_picks" ON momentum_picks;
CREATE POLICY "anon_read_momentum_scans" ON momentum_scans FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read_momentum_picks" ON momentum_picks FOR SELECT TO anon USING (true);

-- ── ML: full-universe feature log (selection-bias fix, ENH-ML-02) ─────────────
-- One row per scanned ticker per scan (NOT just the top picks). This is the
-- de-biased training set for the conviction-weight learner: it also records the
-- tickers the scanner rejected, so the model can learn what separates good
-- setups from bad ones. Labeled end-of-day with the same Fib-hit definition used
-- for picks. `was_pick` flags whether the ticker made the surfaced top-N.
CREATE TABLE IF NOT EXISTS scan_features (
    id               BIGSERIAL PRIMARY KEY,
    scan_id          BIGINT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    trade_date       DATE,
    et_time          TEXT,
    ticker           TEXT NOT NULL,
    company          TEXT,
    sector           TEXT,
    direction        TEXT,        -- bull / bear / neutral (this ticker's own bias)
    was_pick         BOOLEAN NOT NULL DEFAULT FALSE,  -- made the surfaced top-N?
    net_score        INT,
    conviction       NUMERIC,     -- conviction % (0–100)
    weighted_score   NUMERIC,
    grade            TEXT,
    price            NUMERIC,
    chg_pct          NUMERIC,
    mtf_aligned      BOOLEAN,
    earnings_soon    BOOLEAN,
    atr_stop         NUMERIC,
    fib_target       NUMERIC,     -- next-hour Fibonacci target
    fib_label        TEXT,
    signals          JSONB,       -- {"Candle": {"bias": "bull", "label": "..."}, ...}
    fib_hit          BOOLEAN,     -- set EOD: did price hit target within 1 hr?
    fib_window_high  NUMERIC,
    fib_window_low   NUMERIC,
    fib_validated_at TIMESTAMPTZ,
    phit             NUMERIC      -- model P(fib target hit) at scan time, 0–1
);

ALTER TABLE scan_features ADD COLUMN IF NOT EXISTS phit NUMERIC;

CREATE INDEX IF NOT EXISTS idx_scan_features_scan_id ON scan_features (scan_id);
CREATE INDEX IF NOT EXISTS idx_scan_features_day     ON scan_features (trade_date DESC, direction);
CREATE INDEX IF NOT EXISTS idx_scan_features_label   ON scan_features (trade_date DESC)
    WHERE fib_target IS NOT NULL AND fib_hit IS NULL;

-- ── ML: weight-tuning run history (ENH-ML-03) ─────────────────────────────────
-- One row per `python -m backtest.logistic_tuner` run. Powers the dashboard's
-- Machine Learning tab: learned weights, model metrics, and the context/regime
-- coefficients the model used.
CREATE TABLE IF NOT EXISTS ml_weight_runs (
    id             BIGSERIAL PRIMARY KEY,
    run_ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
    trade_date     DATE,
    et_time        TEXT,
    source         TEXT,          -- "features" (de-biased) | "picks"
    lookback_days  INT,           -- NULL = all history
    n_samples      INT,
    n_hits         INT,
    n_misses       INT,
    base_rate      NUMERIC,       -- hit rate of the training set (%)
    train_acc      NUMERIC,       -- in-sample accuracy (%)
    test_acc       NUMERIC,       -- walk-forward test accuracy (%)
    test_auc       NUMERIC,       -- walk-forward AUC
    n_train        INT,
    n_test         INT,
    use_regime     BOOLEAN,
    use_context    BOOLEAN,
    c_param        NUMERIC,       -- inverse L2 strength
    applied        BOOLEAN NOT NULL DEFAULT FALSE,  -- written to conviction.py?
    weights        JSONB,         -- [{"signal","old","new","coef"}, ...]
    context_coefs  JSONB,         -- [{"name","coef"}, ...]
    selection_bias JSONB          -- {"pick_hit_rate","nonpick_hit_rate","n_pick","n_nonpick"}
);

CREATE INDEX IF NOT EXISTS idx_ml_weight_runs_ts ON ml_weight_runs (run_ts DESC);

-- Dashboard read access (anon)
GRANT SELECT ON scan_features, ml_weight_runs TO anon, authenticated;

ALTER TABLE scan_features  ENABLE ROW LEVEL SECURITY;
ALTER TABLE ml_weight_runs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "anon_read_scan_features"  ON scan_features;
DROP POLICY IF EXISTS "anon_read_ml_weight_runs" ON ml_weight_runs;
CREATE POLICY "anon_read_scan_features"  ON scan_features  FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read_ml_weight_runs" ON ml_weight_runs FOR SELECT TO anon USING (true);
