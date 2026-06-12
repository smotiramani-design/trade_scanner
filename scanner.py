"""
scanner.py — full scan pipeline with session-aware price sourcing.

Price source by session:
  Pre-market   → /stable/premarket-quote  (4:00–9:30 AM ET)
  Market open  → /stable/quote real-time  (9:30–4:00 PM ET)
  After-hours  → /stable/aftermarket-quote (4:00–8:00 PM ET)
  Closed       → /stable/quote previousClose
  Final fallback → last OHLCV bar close
"""
import logging
from typing import Dict, List, Optional

import config
from data.fmp_client import (
    get_quotes_batched, get_extended_anchor_data,
    extract_price, extract_chg_pct, extract_session_label,
    get_market_session, MarketSession, FMPError,
    get_company_names,
    get_sp500_constituents, get_nasdaq100_constituents, get_dowjones_constituents,
)
from data.yahoo_client import get_bars, is_market_open, Bar
from signals import run_all
from signals.base import TickerAnalysis
from signals.fibonacci import compute_fibonacci
from universes import get_tickers, MAJOR_US_MARKETS

log = logging.getLogger(__name__)


def resolve_universe(
    universe: str,
    max_tickers: int = 0,
    live_index: bool = True,
) -> List[str]:
    tickers: List[str] = []

    if universe == "major_us_markets":
        if live_index:
            sp  = get_sp500_constituents()
            ndx = get_nasdaq100_constituents()
            dj  = get_dowjones_constituents()
            if sp or ndx or dj:
                seen, merged = set(), []
                for t in sp + ndx + dj:
                    if t not in seen:
                        seen.add(t)
                        merged.append(t)
                tickers = sorted(merged)
                log.info("major_us_markets (live): %d unique tickers", len(tickers))
        if not tickers:
            tickers = list(MAJOR_US_MARKETS)
            log.info("major_us_markets (built-in): %d unique tickers", len(tickers))

    elif universe in ("sp500", "nasdaq100", "dowjones"):
        if live_index:
            try:
                live = {
                    "sp500":     get_sp500_constituents,
                    "nasdaq100": get_nasdaq100_constituents,
                    "dowjones":  get_dowjones_constituents,
                }[universe]()
                if live:
                    tickers = live
            except Exception:
                pass
        if not tickers:
            tickers = get_tickers(universe, 0)

    elif universe == "nyse_american":
        tickers = get_tickers("nyse_american", 0)
        log.info("nyse_american: %d tickers (static list)", len(tickers))

    else:
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
    Run full signal + Fibonacci scan.
    Returns TickerAnalysis list sorted by net_score descending.
    """
    # Detect session once for the whole scan run
    session   = get_market_session()
    mkt_open  = (session == MarketSession.OPEN) if market_open is None else market_open
    mode      = "Hourly" if mkt_open else "Daily"
    session_label = extract_session_label(session)

    log.info("Scan start: %d tickers · %s · %s",
             len(tickers), session_label, mode)

    # ── Fetch standard quotes (all plans) ─────────────────────────────────────
    log.info("Fetching quotes from FMP (%s)…", session_label)
    try:
        quotes: Dict = get_quotes_batched(tickers, config.FMP_BATCH_SIZE)
    except FMPError as e:
        log.error("FMP quote fetch failed: %s", e)
        quotes = {}

    # ── Fetch extended-hours quotes + anchor data ─────────────────────────────
    # get_extended_anchor_data calls premarket-quote or aftermarket-quote
    # based on current session, plus extracts dayHigh/dayLow from standard quote
    # ── Fetch company names (one call for all tickers) ───────────────────────────
    log.info("Fetching company names…")
    company_names: Dict[str, str] = {}
    try:
        company_names = get_company_names(tickers)
        named = sum(1 for v in company_names.values() if v)
        log.info("Company names resolved: %d/%d", named, len(tickers))
    except Exception as e:
        log.debug("Company name fetch failed: %s", e)

    log.info("Fetching extended-hours + anchor data…")
    anchor_data: Dict = {}
    try:
        anchor_data = get_extended_anchor_data(tickers)
    except Exception as e:
        log.debug("Anchor data fetch skipped: %s", e)

    # ── Fetch all OHLCV bars concurrently (ENH-06 async) ────────────────────
    from data.yahoo_client import get_bars_batch
    log.info("Fetching OHLCV bars (async, %d workers)…", config.ASYNC_FETCH_WORKERS)
    all_bars: Dict[str, List[Bar]] = get_bars_batch(tickers, mkt_open)

    # ── Fetch daily bars for multi-timeframe confirmation (ENH-16) ────────────
    daily_bars: Dict[str, List[Bar]] = {}
    if mkt_open:
        log.info("Fetching daily bars for multi-timeframe confirmation…")
        daily_bars = get_bars_batch(tickers, market_open=False)

    # ── Fetch SPY bars once for Relative Strength signal (ENH-09) ────────────
    log.info("Fetching SPY bars for Relative Strength signal…")
    spy_bars: List[Bar] = []
    try:
        from data.yahoo_client import get_bars as _get_bars
        spy_bars = _get_bars("SPY", mkt_open)
        log.debug("SPY: %d bars fetched", len(spy_bars))
    except Exception as e:
        log.debug("SPY bars unavailable: %s", e)

    # ── Earnings calendar — flag tickers with earnings within 2 days (ENH-11) ─
    from data.fmp_client import get_earnings_flags
    log.info("Fetching earnings calendar…")
    earnings_flags: Dict[str, bool] = {}
    try:
        earnings_flags = get_earnings_flags(tickers, days_ahead=2)
        flagged = sum(1 for v in earnings_flags.values() if v)
        if flagged:
            log.info("Earnings within 2 days: %d tickers flagged", flagged)
    except Exception as e:
        log.debug("Earnings calendar fetch failed: %s", e)

    results: List[TickerAnalysis] = []
    total = len(tickers)

    for i, ticker in enumerate(tickers, 1):
        if progress_cb:
            progress_cb(i, total, ticker)

        q      = quotes.get(ticker, {})
        anchor = anchor_data.get(ticker, {})
        ext_q  = anchor.get("_ext_raw", {})

        # ── Session-aware price extraction ────────────────────────────────────
        price = extract_price(q, session, ext_q if ext_q else None)
        chg   = extract_chg_pct(q, session, ext_q if ext_q else None)
        vol   = float(q.get("volume") or 0)

        # ── Fibonacci anchor ──────────────────────────────────────────────────
        day_high  = anchor.get("day_high") or q.get("dayHigh")
        day_low   = anchor.get("day_low")  or q.get("dayLow")
        ext_price = anchor.get("ext_price")
        pm_high: Optional[float] = None
        pm_low:  Optional[float] = None
        if ext_price and ext_price > 0:
            if day_high and float(day_high) > ext_price:
                pm_high = ext_price
            if day_low and float(day_low) < ext_price:
                pm_low = ext_price
        elif day_high and day_low:
            pm_high = float(day_high) if float(day_high) > (price or 0) else None
            pm_low  = float(day_low)  if float(day_low)  < (price or 0) else None

        # ── OHLCV bars (already fetched) ──────────────────────────────────────
        bars: List[Bar] = all_bars.get(ticker, [])
        if not bars or len(bars) < 30:
            log.debug("%s: skipped — only %d bars", ticker, len(bars) if bars else 0)
            continue

        if not price or price <= 0:
            price = bars[-1].close

        # ── Signals (9: 7 core + RS + VWAP) ─────────────────────────────────
        from signals import run_all
        sigs = run_all(bars, spy_bars=spy_bars or None, mode=mode, ticker=ticker)

        company_name = company_names.get(ticker, "")
        ta = TickerAnalysis(
            ticker=ticker,
            price=round(price, 2),
            chg_pct=round(chg, 4),
            volume=vol,
            bars=len(bars),
            mode=mode,
            company_name=company_name,
            signals=sigs,
        )

        # ── Multi-timeframe confirmation (ENH-16) ─────────────────────────────
        d_bars = daily_bars.get(ticker, [])
        if mkt_open and len(d_bars) >= 30:
            from signals.multi_timeframe import check_alignment
            ta.mtf_aligned, ta.mtf_detail = check_alignment(bars, d_bars, ta.net_score)
        else:
            ta.mtf_aligned = True   # no daily bars → don't penalise
            ta.mtf_detail  = ""

        # ── Earnings flag (ENH-11) ────────────────────────────────────────────
        ta.earnings_soon = earnings_flags.get(ticker, False)

        # ── Fibonacci ─────────────────────────────────────────────────────────
        from signals.fibonacci import compute_fibonacci
        ta.fib = compute_fibonacci(
            ticker=ticker,
            bars=bars,
            current_price=price,
            net_score=ta.net_score,
            premarket_high=pm_high,
            premarket_low=pm_low,
        )

        # ── ATR-based stop override (ENH-10) ──────────────────────────────────
        from signals.atr import compute_atr_stop
        ta.atr_stop = compute_atr_stop(bars, price, ta.net_score)

        results.append(ta)

    results.sort(key=lambda r: r.net_score, reverse=True)
    log.info("Scan complete: %d/%d tickers analyzed [%s]",
             len(results), total, session_label)
    return results
