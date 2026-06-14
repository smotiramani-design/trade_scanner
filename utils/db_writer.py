"""
utils/db_writer.py — persist scan results + trades to Postgres (Supabase).

This replaces the hourly email: instead of mailing the top picks, each scan
writes one `scans` row plus its `picks` and `trades` rows. Browse them in the
Supabase Table Editor.

Usage:
    from utils.db_writer import write_scan
    write_scan(results, bulls, bears,
               bull_decisions, bear_decisions,
               session="open", universe="watchlist",
               mode="Hourly", trade_run=True)

psycopg (v3) is imported lazily so the rest of the codebase still works on
machines where the Postgres driver isn't installed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import config
from signals import SIG_NAMES
from signals.base import TickerAnalysis
from signals.conviction import ConvictionScore

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

_SCHEMA_FILE = Path(__file__).parent.parent / "db" / "schema.sql"
_initialized = False


def _connect():
    """Open a psycopg connection from config.DATABASE_URL (lazy import)."""
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set — cannot connect to the database.")
    import psycopg   # lazy: only required when the DB is actually used
    return psycopg.connect(config.DATABASE_URL)


def init_db(conn=None) -> None:
    """Create tables if they don't exist. Safe to call repeatedly."""
    global _initialized
    if _initialized:
        return
    if not _SCHEMA_FILE.exists():
        log.warning("Schema file missing (%s) — skipping init_db", _SCHEMA_FILE)
        return
    sql = _SCHEMA_FILE.read_text()
    own = conn is None
    conn = conn or _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        _initialized = True
        log.info("Database schema ready.")
    finally:
        if own:
            conn.close()


def _signals_json(ta: TickerAnalysis) -> dict:
    """Serialize the signal set as {name: {bias, label}} — mirrors exporter._row."""
    out = {}
    for i, sig in enumerate(ta.signals):
        name = SIG_NAMES[i] if i < len(SIG_NAMES) else f"sig_{i}"
        out[name] = {"bias": sig.bias.value, "label": sig.label}
    return out


def _fib_target(ta: TickerAnalysis) -> Tuple[Optional[float], Optional[str]]:
    fib = getattr(ta, "fib", None)
    if fib and getattr(fib, "next_hour_target", None):
        return float(fib.next_hour_target), getattr(fib, "next_hour_label", None)
    return None, None


def _pick_row(scan_id: int, ta: TickerAnalysis, cs: ConvictionScore,
              direction: str, rank: int, trade_date, et_time: str) -> tuple:
    import json
    fib_t, fib_l = _fib_target(ta)
    atr = getattr(ta, "atr_stop", None)
    return (
        scan_id, trade_date, et_time,
        ta.ticker, ta.company_name or None, getattr(ta, "sector", "") or None,
        direction, rank,
        ta.price, ta.chg_pct, ta.net_score,
        cs.conviction_pct, cs.weighted_score, cs.grade, ta.verdict,
        cs.analysis or None,
        json.dumps(cs.key_signals or []),
        json.dumps(cs.conflicting or []),
        fib_t, fib_l,
        bool(getattr(ta, "mtf_aligned", True)),
        bool(getattr(ta, "earnings_soon", False)),
        float(atr) if atr else None,
        json.dumps(_signals_json(ta)),
    )


def _trade_rows(scan_id: int, decisions: Sequence, dry_run: bool,
                trade_date, et_time: str) -> List[tuple]:
    rows = []
    for d in decisions or []:
        order_id = None
        status = d.action
        if getattr(d, "order_result", None) is not None:
            order_id = getattr(d.order_result, "order_id", None)
            status = "executed" if d.executed else "failed"
        elif dry_run and d.action in ("buy", "sell"):
            status = "dry_run"
        rows.append((
            scan_id, trade_date, et_time, d.ticker, d.action, d.reason,
            d.qty or None, d.entry_price, d.stop_loss, d.take_profit,
            d.size_usd or None, order_id, status, bool(dry_run),
        ))
    return rows


def write_scan(
    results:        List[TickerAnalysis],
    bulls:          List[Tuple[TickerAnalysis, ConvictionScore]],
    bears:          List[Tuple[TickerAnalysis, ConvictionScore]],
    bull_decisions: Optional[Sequence] = None,
    bear_decisions: Optional[Sequence] = None,
    *,
    session:    str = "",
    universe:   str = "",
    mode:       str = "",
    trade_run:  bool = False,
    dry_run:    bool = False,
) -> Optional[int]:
    """
    Write one scan + its picks + its trades in a single transaction.
    Returns the new scan id, or None if the DB is disabled/unavailable.
    """
    if not config.DB_ENABLED:
        log.debug("DB_ENABLED=false — skipping database write.")
        return None

    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET)
    trade_date = now_et.date()
    et_time = now_et.strftime("%H:%M")
    et_hour = now_et.hour

    conn = _connect()
    try:
        init_db(conn)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO scans
                   (run_ts, trade_date, et_time, et_hour, session, universe, mode,
                    n_results, trade_run)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (now_utc, trade_date, et_time, et_hour, session or None,
                 universe or None, mode or None, len(results), trade_run),
            )
            scan_id = cur.fetchone()[0]

            pick_rows = (
                [_pick_row(scan_id, ta, cs, "bull", i, trade_date, et_time)
                 for i, (ta, cs) in enumerate(bulls, 1)]
                + [_pick_row(scan_id, ta, cs, "bear", i, trade_date, et_time)
                   for i, (ta, cs) in enumerate(bears, 1)]
            )
            if pick_rows:
                cur.executemany(
                    """INSERT INTO picks
                       (scan_id, trade_date, et_time, ticker, company, sector,
                        direction, rank, price, chg_pct,
                        net_score, conviction, weighted_score, grade, verdict,
                        analysis, key_signals, conflicting, fib_target, fib_label,
                        mtf_aligned, earnings_soon, atr_stop, signals)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    pick_rows,
                )

            trade_rows = (
                _trade_rows(scan_id, bull_decisions, dry_run, trade_date, et_time)
                + _trade_rows(scan_id, bear_decisions, dry_run, trade_date, et_time)
            )
            if trade_rows:
                cur.executemany(
                    """INSERT INTO trades
                       (scan_id, trade_date, et_time, ticker, action, reason, qty,
                        entry_price, stop_loss, take_profit, size_usd, order_id,
                        status, dry_run)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    trade_rows,
                )

        conn.commit()
        log.info("DB write: scan #%d — %d picks, %d trade rows.",
                 scan_id, len(pick_rows), len(trade_rows))
        return scan_id
    except Exception:
        conn.rollback()
        log.exception("DB write failed — rolled back.")
        raise
    finally:
        conn.close()
