"""
daily/db_writer.py — persist the daily conviction + Fibonacci scan.

Writes one momentum_scans row plus its momentum_picks rows (top 10 long + top 10
short). Uses the SAME momentum tables the pre-market screener used, now extended
(see db/schema.sql) with direction / conviction / grade / net_score / the full Fib
plan / the whole-day target. The 4 PM validator (daily/validate.py) later fills in
target_hit / day_high / day_low.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

import config
from signals import SIG_NAMES
from signals.base import TickerAnalysis
from signals.conviction import ConvictionScore

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def _connect():
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set — cannot connect to the database.")
    import psycopg
    return psycopg.connect(config.DATABASE_URL)


def _signals_json(ta: TickerAnalysis) -> dict:
    out = {}
    for i, sig in enumerate(ta.signals):
        name = SIG_NAMES[i] if i < len(SIG_NAMES) else f"sig_{i}"
        out[name] = {"bias": sig.bias.value, "label": sig.label}
    return out


def _f(val) -> Optional[float]:
    return float(val) if val is not None else None


def _pick_row(
    scan_id: int,
    ta: TickerAnalysis,
    cs: ConvictionScore,
    direction: str,
    rank: int,
    trade_date,
    et_time: str,
) -> tuple:
    fib = getattr(ta, "fib", None)
    day_target = getattr(fib, "next_hour_target", None) if fib else None
    day_label = getattr(fib, "next_hour_label", "") if fib else ""
    return (
        scan_id, trade_date, et_time,
        ta.ticker, ta.company_name or None, getattr(ta, "sector", "") or None,
        "TRADE",                       # tier retained for backward-compat (all actionable)
        direction, rank,
        ta.net_score, round(cs.conviction_pct, 1), cs.grade,
        _f(ta.price), _f(ta.chg_pct),
        cs.analysis or None,
        json.dumps(cs.key_signals or []),
        json.dumps(_signals_json(ta)),
        cs.phit,
        getattr(fib, "direction", None) if fib else None,
        _f(getattr(fib, "entry_price", None)) if fib else None,
        _f(getattr(fib, "stop_loss", None)) if fib else None,
        _f(getattr(fib, "target_1", None)) if fib else None,
        _f(getattr(fib, "target_2", None)) if fib else None,
        _f(getattr(fib, "target_3", None)) if fib else None,
        _f(day_target),
        day_label or None,
    )


def write_daily_scan(
    bulls: List[Tuple[TickerAnalysis, ConvictionScore]],
    bears: List[Tuple[TickerAnalysis, ConvictionScore]],
    *,
    universe: str = "",
    run_time: Optional[datetime] = None,
) -> Optional[int]:
    """Write one daily scan + its long/short picks in a single transaction."""
    if not config.DB_ENABLED:
        log.debug("DB_ENABLED=false — skipping database write.")
        return None

    now_utc = datetime.now(timezone.utc)
    if run_time is not None:
        now_utc = (run_time.replace(tzinfo=ET) if run_time.tzinfo is None
                   else run_time).astimezone(timezone.utc)
    now_et = now_utc.astimezone(ET)
    trade_date = now_et.date()
    et_time = now_et.strftime("%H:%M")
    et_hour = now_et.hour
    n_long, n_short = len(bulls), len(bears)

    from utils.db_writer import init_db   # shared schema loader (creates/upgrades tables)

    conn = _connect()
    try:
        init_db(conn)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO momentum_scans
                   (run_ts, trade_date, et_time, et_hour, session, universe, mode,
                    n_results, n_trade, n_watch, n_skip, n_long, n_short)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (now_utc, trade_date, et_time, et_hour, "premarket",
                 universe or None, "Daily",
                 n_long + n_short, n_long + n_short, 0, 0, n_long, n_short),
            )
            scan_id = cur.fetchone()[0]

            rows = (
                [_pick_row(scan_id, ta, cs, "bull", i, trade_date, et_time)
                 for i, (ta, cs) in enumerate(bulls, 1)]
                + [_pick_row(scan_id, ta, cs, "bear", i, trade_date, et_time)
                   for i, (ta, cs) in enumerate(bears, 1)]
            )
            if rows:
                cur.executemany(
                    """INSERT INTO momentum_picks
                       (scan_id, trade_date, et_time, ticker, company, sector, tier,
                        direction, rank, net_score, conviction, grade, price, chg_pct,
                        analysis, key_signals, signals, phit,
                        fib_direction, fib_entry, fib_stop, fib_t1, fib_t2, fib_t3,
                        day_target, day_target_label)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    rows,
                )

        conn.commit()
        log.info("DB write: daily scan #%d — %d long + %d short picks.",
                 scan_id, n_long, n_short)
        return scan_id
    except Exception:
        conn.rollback()
        log.exception("Daily DB write failed — rolled back.")
        raise
    finally:
        conn.close()
