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
--   trades — trade decisions made during the 9:35 / 11:35 / 2:35 windows
--
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
    fib_target     NUMERIC,     -- next-hour Fibonacci target
    fib_label      TEXT,
    mtf_aligned    BOOLEAN,     -- multi-timeframe confirmation
    earnings_soon  BOOLEAN,     -- earnings within 2 days
    atr_stop       NUMERIC,
    signals        JSONB        -- {"Candle pattern": {"bias": "bull", "label": "..."}, ...}
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
-- This is the table to open in Supabase. Filter trade_date / et_hour, sort by
-- conviction to see the best stocks for any given day and hour.
CREATE OR REPLACE VIEW v_scan_picks AS
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
    p.mtf_aligned,
    p.earnings_soon,
    p.verdict,
    s.universe,
    s.trade_run,
    s.run_ts,
    p.scan_id
FROM picks p
JOIN scans s ON s.id = p.scan_id
ORDER BY s.run_ts DESC, p.direction, p.rank;

-- ── Convenience view: just today's picks (ET) ─────────────────────────────────
CREATE OR REPLACE VIEW v_today_picks AS
SELECT * FROM v_scan_picks
WHERE trade_date = (now() AT TIME ZONE 'America/New_York')::date;
