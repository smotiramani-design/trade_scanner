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
    fib_target     NUMERIC,     -- next-hour Fibonacci target
    fib_label      TEXT,
    fib_hit        BOOLEAN,     -- set at 4 PM: did price hit target within 1 hr?
    fib_window_high NUMERIC,    -- high in the validation window
    fib_window_low  NUMERIC,    -- low in the validation window
    fib_validated_at TIMESTAMPTZ,
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
ALTER TABLE picks  ADD COLUMN IF NOT EXISTS fib_hit           BOOLEAN;
ALTER TABLE picks  ADD COLUMN IF NOT EXISTS fib_window_high   NUMERIC;
ALTER TABLE picks  ADD COLUMN IF NOT EXISTS fib_window_low    NUMERIC;
ALTER TABLE picks  ADD COLUMN IF NOT EXISTS fib_validated_at  TIMESTAMPTZ;
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
    p.fib_hit,
    p.fib_window_high,
    p.fib_window_low,
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
