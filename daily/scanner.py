"""
daily/scanner.py — once-a-day scan reusing the intraday conviction + Fibonacci engine.

Runs the full 10-signal + market-sentiment scan on DAILY bars across the configured
universe (default: major_us_markets = S&P 500 + Nasdaq 100 + Russell 1000), then
selects the top N bullish (long) and top N bearish (short) picks by the same
conviction / P(hit) ranking the intraday scanner uses.

Each pick carries a whole-day Fibonacci target (the primary take-profit level on the
correct side of price) — interpreted as the target to be reached by the 4 PM close.
Results persist to the momentum_scans / momentum_picks tables that drive the
dashboard's "Daily Momentum" tab.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

import config
from scanner import resolve_universe, scan
from signals.base import TickerAnalysis
from signals.conviction import top_picks

log = logging.getLogger(__name__)


def run_daily_scan(
    universe: Optional[str] = None,
    top_n: int = 10,
    run_time: Optional[datetime] = None,
    write_db: bool = True,
) -> dict:
    """
    Execute the daily scan and (optionally) persist it.

    Args:
        universe:  universe key; defaults to config.DEFAULT_UNIVERSE.
        top_n:     number of longs and shorts to keep (10 each by default).
        run_time:  ET timestamp to stamp the run with (defaults to now); the
                   scheduler passes the 09:15 trigger time here.
        write_db:  write results to momentum_scans / momentum_picks.

    Returns a JSON-serialisable summary dict.
    """
    universe = universe or config.DEFAULT_UNIVERSE
    tickers = resolve_universe(universe, config.MAX_TICKERS)

    # Merge personal watchlist first, mirroring intraday main.py.
    if config.PERSONAL_WATCHLIST:
        extra = [t for t in config.PERSONAL_WATCHLIST if t not in tickers]
        if extra:
            tickers = extra + tickers

    if not tickers:
        log.error("Daily scan: no tickers resolved for universe '%s'", universe)
        return {"status": "error", "reason": "no_tickers", "universe": universe}

    log.info("Daily scan start: universe=%s · %d tickers · DAILY bars",
             universe, len(tickers))

    # Force DAILY bars — the daily scan always targets the whole-day horizon,
    # regardless of the wall-clock time the job fires (e.g. 09:15 pre-market).
    results: List[TickerAnalysis] = scan(tickers, market_open=False)
    if not results:
        log.error("Daily scan returned no results (check FMP key / tickers).")
        return {"status": "error", "reason": "no_results", "universe": universe}

    bulls, bears = top_picks(results, top_n)
    log.info("Daily scan: %d long + %d short selected from %d analyzed",
             len(bulls), len(bears), len(results))

    scan_id = None
    if write_db:
        if config.DB_ENABLED:
            from daily.db_writer import write_daily_scan
            scan_id = write_daily_scan(bulls, bears, universe=universe, run_time=run_time)
        else:
            log.warning("DB_ENABLED=false — daily scan not persisted. Set DATABASE_URL.")

    return {
        "status": "ok",
        "universe": universe,
        "analyzed": len(results),
        "longs": len(bulls),
        "shorts": len(bears),
        "scan_id": scan_id,
    }
