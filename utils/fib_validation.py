"""
utils/fib_validation.py — End-of-day Fib target hit validation.

For each pick on trade_date with a fib_target, check whether price reached
the target within the 60 minutes after that scan's run_ts — but only if the
trade would still be open under automation:

  1. Entry must fill first (if fib_entry is set)
  2. After entry, target must be touched BEFORE the stop
  3. If stop is hit first (or on the same bar as the target), it is a MISS

This matches live automation: a stop fill auto-sells, so a later target touch
does not count as a hit.

Runs hourly so each pick is graded once its 1-hour window has closed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import config

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
MARKET_CLOSE = (16, 0)   # 4:00 PM ET — regular session end for window cap

# Bar tuple: (timestamp_et, open, high, low)
BarHL = Tuple[datetime, float, float, float]


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


def _load_intraday_bars(ticker: str, trade_date) -> List[BarHL]:
    """Load (timestamp_et, open, high, low) bars for one ticker on trade_date."""
    from data.yahoo_client import Bar, _fmp_bars_to_bar_list, _yfinance_bars

    rows: List[BarHL] = []

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
                        rows.append((ts, float(b.open), float(b.high), float(b.low)))
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
                rows.append((ts, float(b.open), float(b.high), float(b.low)))
        rows.sort(key=lambda x: x[0])
    except Exception as e:
        log.debug("yfinance intraday failed for %s: %s", ticker, e)

    return rows


def _bars_in_window(
    bars: Sequence[BarHL],
    start_et: datetime,
    end_et: datetime,
) -> List[BarHL]:
    """Filter bars overlapping [start_et, end_et)."""
    out: List[BarHL] = []
    for ts, o, hi, lo in bars:
        if ts >= end_et:
            break
        # Include the bar if it overlaps the window (bar can start slightly before).
        if ts + timedelta(minutes=59) >= start_et and ts < end_et:
            out.append((ts, o, hi, lo))
    return out


def _window_extremes(bars: Sequence[BarHL]) -> Tuple[Optional[float], Optional[float]]:
    if not bars:
        return None, None
    return max(b[2] for b in bars), min(b[3] for b in bars)


def _entry_filled(direction: str, entry: float, o: float, hi: float, lo: float) -> bool:
    """True if this bar would fill a limit-style Fib entry."""
    if direction == "bull":
        # Long pullback: fill when price trades down to (or through) entry.
        return lo <= entry
    if direction == "bear":
        # Short rally: fill when price trades up to (or through) entry.
        return hi >= entry
    return False


def _stop_hit(direction: str, stop: float, o: float, hi: float, lo: float) -> bool:
    if direction == "bull":
        return o <= stop or lo <= stop
    if direction == "bear":
        return o >= stop or hi >= stop
    return False


def _target_hit(direction: str, target: float, hi: float, lo: float) -> bool:
    if direction == "bull":
        return hi >= target
    if direction == "bear":
        return lo <= target
    return False


def evaluate_target_hit(
    direction: str,
    target: float,
    bars: Sequence[BarHL],
    *,
    entry: Optional[float] = None,
    stop: Optional[float] = None,
) -> Optional[bool]:
    """
    Walk bars in time and decide hit vs miss under automation rules.

    Returns:
      True  — entry filled (or no entry required), then target before stop
      False — stop first, never entered, or target never reached
      None  — no bar data

    Same-bar ambiguity: stop wins (matches backtest / live monitor).
    If stop is missing, falls back to target-touch only (legacy rows).
    If entry is missing, treat as entered at the first bar (market at scan).
    """
    if not bars:
        return None
    if direction not in ("bull", "bear"):
        return None

    in_trade = entry is None
    for _ts, o, hi, lo in bars:
        if not in_trade:
            if entry is not None and _entry_filled(direction, entry, o, hi, lo):
                in_trade = True
            else:
                continue

        # In trade: stop before target (conservative same-bar rule).
        if stop is not None and _stop_hit(direction, stop, o, hi, lo):
            return False
        if _target_hit(direction, target, hi, lo):
            return True

    # Never entered, or entered but neither stop nor target → miss.
    return False


def _fetch_window_extremes(
    ticker: str,
    start_et: datetime,
    end_et: datetime,
    cache: Dict[str, List],
) -> Tuple[Optional[float], Optional[float]]:
    """Return (high, low) for [start_et, end_et) using 5-min bars, hourly fallback."""
    if ticker not in cache:
        cache[ticker] = _load_intraday_bars(ticker, start_et.date())

    bars = _bars_in_window(cache[ticker], start_et, end_et)
    return _window_extremes(bars)


def _hit(direction: str, target: float, hi: Optional[float], lo: Optional[float]) -> Optional[bool]:
    """Legacy target-only helper kept for callers/tests; prefer evaluate_target_hit."""
    if hi is None or lo is None:
        return None
    if direction == "bull":
        return hi >= target
    if direction == "bear":
        return lo <= target
    return None


def validate_today_fib_hits(trade_date=None, now=None) -> dict:
    """
    Validate Fib targets for picks on trade_date whose 1-hour window has closed.

    Window start = each scan's run_ts; window end = run_ts + 1 hour (capped at the
    4 PM close). A pick is a HIT only if entry fills and the target is touched
    before the stop — matching automated stop-out behavior.
    """
    if not config.DB_ENABLED:
        log.warning("DB disabled — skipping fib validation.")
        return {"status": "skipped", "reason": "db_disabled"}

    if trade_date is None:
        trade_date = datetime.now(ET).date()
    if now is None:
        now = datetime.now(ET)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    else:
        now = now.astimezone(ET)

    from utils.db_writer import init_db

    conn = _connect()
    bar_cache: Dict[str, List] = {}
    validated = 0
    hits = 0
    misses = 0
    unknown = 0
    pending = 0

    try:
        init_db(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.id, p.ticker, p.direction, p.fib_target,
                       p.fib_entry, p.fib_stop,
                       s.run_ts, p.et_time
                FROM picks p
                JOIN scans s ON s.id = p.scan_id
                WHERE p.trade_date = %s
                  AND p.fib_target IS NOT NULL
                  AND p.fib_hit IS NULL
                ORDER BY s.run_ts, p.id
                """,
                (trade_date,),
            )
            rows = cur.fetchall()

        for (pick_id, ticker, direction, fib_target, fib_entry, fib_stop,
             run_ts, et_time) in rows:
            target = float(fib_target)
            entry = float(fib_entry) if fib_entry is not None else None
            stop = float(fib_stop) if fib_stop is not None else None
            start_et = run_ts.astimezone(ET) if run_ts.tzinfo else run_ts.replace(tzinfo=ET)
            end_et = _parse_window_end(start_et)

            # Skip picks whose 1-hour window hasn't fully elapsed yet — they get
            # graded on the next hourly run once the window closes.
            if end_et > now:
                pending += 1
                continue

            if ticker not in bar_cache:
                bar_cache[ticker] = _load_intraday_bars(ticker, start_et.date())
            window = _bars_in_window(bar_cache[ticker], start_et, end_et)
            hi, lo = _window_extremes(window)
            hit = evaluate_target_hit(direction, target, window, entry=entry, stop=stop)

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

            log.info("%s %s @ %s fib=$%.2f stop=%s → %s (hi=%s lo=%s)",
                     ticker, direction, et_time, target,
                     f"${stop:.2f}" if stop is not None else "—",
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
        "pending": pending,   # windows not yet closed — graded on a later hourly run
    }
    log.info("Fib validation done: %s", summary)
    return summary


def validate_today_feature_hits(trade_date=None, limit: int = 0) -> dict:
    """
    ENH-ML-02: label the full scanned universe (scan_features) with fib_hit.

    Identical Fib-hit definition as picks (entry → target before stop), applied
    to every scanned ticker with a fib_target. Runs at 4 PM ET alongside pick
    validation.

    limit: cap the number of rows validated per day (0 = no cap). Useful to
    bound the intraday bar fetches on very large universes.
    """
    if not config.DB_ENABLED:
        log.warning("DB disabled — skipping feature validation.")
        return {"status": "skipped", "reason": "db_disabled"}

    if trade_date is None:
        trade_date = datetime.now(ET).date()

    from utils.db_writer import init_db

    conn = _connect()
    bar_cache: Dict[str, List] = {}
    validated = hits = misses = unknown = 0

    try:
        init_db(conn)
        limit_sql = " LIMIT %s" if limit and limit > 0 else ""
        params = [trade_date] + ([limit] if limit_sql else [])
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT f.id, f.ticker, f.direction, f.fib_target,
                       f.fib_entry, f.fib_stop, s.run_ts
                FROM scan_features f
                JOIN scans s ON s.id = f.scan_id
                WHERE f.trade_date = %s
                  AND f.fib_target IS NOT NULL
                  AND f.fib_hit IS NULL
                  AND f.direction IN ('bull', 'bear')
                ORDER BY s.run_ts, f.id{limit_sql}
                """,
                params,
            )
            rows = cur.fetchall()

        for feat_id, ticker, direction, fib_target, fib_entry, fib_stop, run_ts in rows:
            target = float(fib_target)
            entry = float(fib_entry) if fib_entry is not None else None
            stop = float(fib_stop) if fib_stop is not None else None
            start_et = run_ts.astimezone(ET) if run_ts.tzinfo else run_ts.replace(tzinfo=ET)
            end_et = _parse_window_end(start_et)

            if ticker not in bar_cache:
                bar_cache[ticker] = _load_intraday_bars(ticker, start_et.date())
            window = _bars_in_window(bar_cache[ticker], start_et, end_et)
            hi, lo = _window_extremes(window)
            hit = evaluate_target_hit(direction, target, window, entry=entry, stop=stop)

            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE scan_features
                       SET fib_hit = %s, fib_window_high = %s, fib_window_low = %s,
                           fib_validated_at = now()
                       WHERE id = %s""",
                    (hit, hi, lo, feat_id),
                )
            conn.commit()

            validated += 1
            if hit is True:
                hits += 1
            elif hit is False:
                misses += 1
            else:
                unknown += 1

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
    log.info("Feature validation done: %s", summary)
    return summary
