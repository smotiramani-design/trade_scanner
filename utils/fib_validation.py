"""
utils/fib_validation.py — End-of-day Fib target hit validation.

For each pick from today's hourly scans (top-of-hour runs), check whether price
reached the Fib target within the next 60 minutes:

  bull → window high >= fib_target
  bear → window low  <= fib_target

Runs once at 4:00 PM ET after the last scan at 3:00 PM.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import config

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
MARKET_CLOSE = (16, 0)   # 4:00 PM ET — regular session end for window cap


def _connect():
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set.")
    import psycopg
    return psycopg.connect(config.DATABASE_URL)


def _parse_window_end(start_et: datetime) -> datetime:
    """Cap the validation window at market close (4:00 PM ET)."""
    end = start_et + timedelta(hours=1)
    close = start_et.replace(hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1],
                             second=0, microsecond=0)
    if start_et.date() == close.date() and end > close:
        end = close
    return end


def _fetch_window_extremes(
    ticker: str,
    start_et: datetime,
    end_et: datetime,
    cache: Dict[str, List],
) -> Tuple[Optional[float], Optional[float]]:
    """Return (high, low) for [start_et, end_et) using 5-min bars, hourly fallback."""
    if ticker not in cache:
        cache[ticker] = _load_intraday_bars(ticker, start_et.date())

    bars = cache[ticker]
    if not bars:
        return None, None

    highs, lows = [], []
    for ts, hi, lo in bars:
        if ts >= end_et:
            break
        if ts + timedelta(minutes=59) >= start_et and ts < end_et:
            highs.append(hi)
            lows.append(lo)

    if not highs:
        return None, None
    return max(highs), min(lows)


def _load_intraday_bars(ticker: str, trade_date) -> List[Tuple[datetime, float, float]]:
    """Load (timestamp_et, high, low) bars for one ticker on trade_date."""
    from data.yahoo_client import Bar, _fmp_bars_to_bar_list, _yfinance_bars

    rows: List[Tuple[datetime, float, float]] = []

    try:
        from data.fmp_client import get_intraday_bars
        for interval in ("5min", "1hour"):
            raw = get_intraday_bars(ticker, interval=interval, days=5)
            if raw:
                for b in _fmp_bars_to_bar_list(raw):
                    ts = b.timestamp
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=ET)
                    else:
                        ts = ts.astimezone(ET)
                    if ts.date() == trade_date:
                        rows.append((ts, b.high, b.low))
                if rows:
                    rows.sort(key=lambda x: x[0])
                    return rows
    except Exception as e:
        log.debug("FMP intraday failed for %s: %s", ticker, e)

    try:
        yf_bars: List[Bar] = _yfinance_bars(ticker, market_open=True)
        for b in yf_bars:
            ts = b.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=ET)
            else:
                ts = ts.astimezone(ET)
            if ts.date() == trade_date:
                rows.append((ts, b.high, b.low))
        rows.sort(key=lambda x: x[0])
    except Exception as e:
        log.debug("yfinance intraday failed for %s: %s", ticker, e)

    return rows


def _hit(direction: str, target: float, hi: Optional[float], lo: Optional[float]) -> Optional[bool]:
    if hi is None or lo is None:
        return None
    if direction == "bull":
        return hi >= target
    if direction == "bear":
        return lo <= target
    return None


def validate_today_fib_hits(trade_date=None) -> dict:
    """
    Validate Fib targets for all hourly-scan picks on trade_date.
    Only picks from top-of-hour scans (et_time ending in :00) are evaluated.
    """
    if not config.DB_ENABLED:
        log.warning("DB disabled — skipping fib validation.")
        return {"status": "skipped", "reason": "db_disabled"}

    if trade_date is None:
        trade_date = datetime.now(ET).date()

    from utils.db_writer import init_db

    conn = _connect()
    bar_cache: Dict[str, List] = {}
    validated = 0
    hits = 0
    misses = 0
    unknown = 0

    try:
        init_db(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.id, p.ticker, p.direction, p.fib_target,
                       s.run_ts, p.et_time
                FROM picks p
                JOIN scans s ON s.id = p.scan_id
                WHERE p.trade_date = %s
                  AND p.fib_target IS NOT NULL
                  AND p.et_time ~ '^[0-9]{2}:00$'
                ORDER BY s.run_ts, p.id
                """,
                (trade_date,),
            )
            rows = cur.fetchall()

        for pick_id, ticker, direction, fib_target, run_ts, et_time in rows:
            target = float(fib_target)
            start_et = run_ts.astimezone(ET) if run_ts.tzinfo else run_ts.replace(tzinfo=ET)
            end_et = _parse_window_end(start_et)

            hi, lo = _fetch_window_extremes(ticker, start_et, end_et, bar_cache)
            hit = _hit(direction, target, hi, lo)

            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE picks
                       SET fib_hit = %s, fib_window_high = %s, fib_window_low = %s,
                           fib_validated_at = now()
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

            log.info("%s %s @ %s fib=$%.2f → %s (hi=%s lo=%s)",
                     ticker, direction, et_time, target,
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
    log.info("Fib validation done: %s", summary)
    return summary
