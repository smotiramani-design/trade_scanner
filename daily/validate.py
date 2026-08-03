"""
daily/validate.py — 4 PM whole-day target-hit validation for the daily scan.

For each momentum pick that has a day_target, check whether price reached the target
between the scan's run_ts (≈09:15 ET) and the 4:00 PM close:

  bull → session high >= day_target
  bear → session low  <= day_target

Writes target_hit / day_high / day_low / validated_at back onto momentum_picks.
Reuses the intraday-bar loader from utils.fib_validation so both scanners share one
data path.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import config

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
MARKET_CLOSE = (16, 0)   # 4:00 PM ET


def _connect():
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set.")
    import psycopg
    return psycopg.connect(config.DATABASE_URL)


def _hit(direction: str, target: float,
         hi: Optional[float], lo: Optional[float]) -> Optional[bool]:
    if hi is None or lo is None:
        return None
    if direction == "bull":
        return hi >= target
    if direction == "bear":
        return lo <= target
    return None


def validate_daily_targets(trade_date=None) -> dict:
    """Validate whole-day Fib targets for every daily pick on trade_date."""
    if not config.DB_ENABLED:
        log.warning("DB disabled — skipping daily target validation.")
        return {"status": "skipped", "reason": "db_disabled"}

    if trade_date is None:
        trade_date = datetime.now(ET).date()

    from utils.db_writer import init_db
    from utils.fib_validation import _load_intraday_bars   # shared loader

    conn = _connect()
    bar_cache: Dict[str, List] = {}
    validated = hits = misses = unknown = 0

    try:
        init_db(conn)
        with conn.cursor() as cur:
            cur.execute(
                """SELECT p.id, p.ticker, p.direction, p.day_target, s.run_ts
                   FROM momentum_picks p
                   JOIN momentum_scans s ON s.id = p.scan_id
                   WHERE p.trade_date = %s
                     AND p.day_target IS NOT NULL
                     AND p.target_hit IS NULL
                     AND p.direction IN ('bull', 'bear')
                   ORDER BY s.run_ts, p.id""",
                (trade_date,),
            )
            rows = cur.fetchall()

        for pick_id, ticker, direction, day_target, run_ts in rows:
            target = float(day_target)
            start_et = run_ts.astimezone(ET) if run_ts.tzinfo else run_ts.replace(tzinfo=ET)
            close_et = start_et.replace(hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1],
                                        second=0, microsecond=0)

            if ticker not in bar_cache:
                bar_cache[ticker] = _load_intraday_bars(ticker, start_et.date())
            bars = bar_cache[ticker]

            highs = [hi for ts, hi, lo in bars if start_et <= ts <= close_et]
            lows = [lo for ts, hi, lo in bars if start_et <= ts <= close_et]
            hi = max(highs) if highs else None
            lo = min(lows) if lows else None
            hit = _hit(direction, target, hi, lo)

            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE momentum_picks
                       SET target_hit = %s, day_high = %s, day_low = %s,
                           validated_at = now()
                       WHERE id = %s""",
                    (hit, hi, lo, pick_id),
                )
            conn.commit()

            validated += 1
            if hit is True:
                hits += 1
            elif hit is False:
                misses += 1
            else:
                unknown += 1

            log.info("%s %s day_target=$%.2f → %s (hi=%s lo=%s)",
                     ticker, direction, target,
                     "HIT" if hit else "MISS" if hit is False else "N/A",
                     f"{hi:.2f}" if hi else "—", f"{lo:.2f}" if lo else "—")
    finally:
        conn.close()

    summary = {
        "status": "ok",
        "trade_date": str(trade_date),
        "validated": validated,
        "hits": hits,
        "misses": misses,
        "unknown": unknown,
    }
    log.info("Daily target validation done: %s", summary)
    return summary
