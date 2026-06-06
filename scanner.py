"""
scanner.py — orchestrates the full scan pipeline:
  1. Resolve ticker universe
  2. Fetch real-time quotes from FMP
  3. Fetch OHLCV history from Yahoo Finance
  4. Run all 7 signals
  5. Return sorted TickerAnalysis list
"""
import logging
from typing import Dict, List, Optional

import config
from data.fmp_client import get_quotes_batched, FMPError, \
    get_sp500_constituents, get_nasdaq100_constituents, get_dowjones_constituents
from data.yahoo_client import get_bars, is_market_open, Bar
from signals import run_all
from signals.base import TickerAnalysis
from universes import get_tickers

log = logging.getLogger(__name__)


def resolve_universe(universe: str, max_tickers: int = 0, live_index: bool = True) -> List[str]:
    """
    Return the ticker list for a universe name.
    If live_index=True, tries to fetch live constituent lists from FMP first.
    """
    tickers: List[str] = []
    if live_index:
        try:
            if universe == "sp500":
                tickers = get_sp500_constituents()
            elif universe == "nasdaq100":
                tickers = get_nasdaq100_constituents()
            elif universe == "dowjones":
                tickers = get_dowjones_constituents()
        except Exception:
            pass

    if not tickers:
        tickers = get_tickers(universe, 0)

    if max_tickers and max_tickers < len(tickers):
        tickers = tickers[:max_tickers]

    log.info("Universe '%s': %d tickers", universe, len(tickers))
    return tickers


def scan(
    tickers: List[str],
    market_open: Optional[bool] = None,
    progress_cb=None,
) -> List[TickerAnalysis]:
    """
    Run a full scan for the given ticker list.

    Args:
        tickers:     list of ticker symbols
        market_open: override market-hours detection (None = auto-detect)
        progress_cb: optional callable(done, total, ticker) for progress updates

    Returns:
        list of TickerAnalysis sorted by net_score descending
    """
    if market_open is None:
        market_open = is_market_open()
    mode = "Hourly" if market_open else "Daily"
    log.info("Starting scan: %d tickers · mode=%s", len(tickers), mode)

    log.info("Fetching real-time quotes from FMP…")
    try:
        quotes: Dict = get_quotes_batched(tickers, config.FMP_BATCH_SIZE)
    except FMPError as e:
        log.error("FMP quote fetch failed: %s", e)
        quotes = {}

    results: List[TickerAnalysis] = []
    total = len(tickers)

    for i, ticker in enumerate(tickers, 1):
        log.debug("[%d/%d] Analyzing %s", i, total, ticker)
        if progress_cb:
            progress_cb(i, total, ticker)

        q     = quotes.get(ticker, {})
        price = q.get("price") or 0.0
        chg   = q.get("changesPercentage") or 0.0
        vol   = q.get("volume") or 0.0

        bars: List[Bar] = get_bars(ticker, market_open)
        if not bars or len(bars) < 30:
            log.debug("%s: skipped (only %d bars)", ticker, len(bars) if bars else 0)
            continue

        sigs = run_all(bars)
        results.append(TickerAnalysis(
            ticker=ticker,
            price=price,
            chg_pct=chg,
            volume=vol,
            bars=len(bars),
            mode=mode,
            signals=sigs,
        ))

    results.sort(key=lambda r: r.net_score, reverse=True)
    log.info("Scan complete: %d tickers analyzed", len(results))
    return results
