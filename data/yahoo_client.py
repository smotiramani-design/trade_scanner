"""
data/yahoo_client.py — OHLCV bar fetcher with async batch support.

ENH-06: Async/concurrent OHLCV fetch.
  get_bars_batch_async() replaces the sequential get_bars_batch().
  Uses asyncio + ThreadPoolExecutor to fetch all tickers concurrently.
  600-ticker scan: ~75s sequential → ~12s async (50× worker threads).

Strategy (market open / intraday mode):
  1. FMP /stable/historical-chart/1hour (Ultimate plan) — real-time
  2. Fall back to yfinance hourly (15-min delayed)

Strategy (market closed / daily mode):
  1. yfinance daily — reliable, fast, 1-year history
"""
import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import yfinance as yf

import config

log = logging.getLogger(__name__)

# Max concurrent Yahoo Finance requests — above ~50 triggers rate limiting
_MAX_WORKERS = min(config.ASYNC_FETCH_WORKERS, 50)


@dataclass
class Bar:
    timestamp: datetime
    open:      float
    high:      float
    low:       float
    close:     float
    volume:    float

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open


def is_market_open() -> bool:
    """Return True if US equity market is currently open (ET 9:30–16:00 Mon–Fri)."""
    try:
        from data.fmp_client import get_market_session, MarketSession
        return get_market_session() == MarketSession.OPEN
    except Exception:
        try:
            from zoneinfo import ZoneInfo
            now_et = datetime.now(tz=ZoneInfo("America/New_York"))
        except ImportError:
            import pytz
            now_et = datetime.now(tz=pytz.timezone("America/New_York"))
        if now_et.weekday() >= 5:
            return False
        mins = now_et.hour * 60 + now_et.minute
        return 570 <= mins < 960


def _fmp_bars_to_bar_list(raw: List[dict]) -> List[Bar]:
    """Convert FMP intraday JSON (newest-first) to oldest-first Bar list."""
    bars = []
    for d in reversed(raw):
        try:
            bars.append(Bar(
                timestamp=datetime.fromisoformat(d["date"]),
                open=float(d["open"]),
                high=float(d["high"]),
                low=float(d["low"]),
                close=float(d["close"]),
                volume=float(d.get("volume") or 0),
            ))
        except (KeyError, ValueError, TypeError):
            continue
    return [b for b in bars if b.open and b.high and b.low and b.close]


def _yfinance_bars(ticker: str, market_open: bool) -> List[Bar]:
    """Fetch bars from yfinance (used for both sync and async paths)."""
    interval = "1h" if market_open else "1d"
    period   = "3mo" if market_open else "1y"
    try:
        tk  = yf.Ticker(ticker)
        df  = tk.history(period=period, interval=interval, auto_adjust=True)
        if df.empty:
            return []
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        return [
            Bar(
                timestamp=idx.to_pydatetime(),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row.get("Volume") or 0),
            )
            for idx, row in df.iterrows()
        ]
    except Exception as e:
        log.debug("%s: yfinance error — %s", ticker, e)
        return []


def get_bars(ticker: str, market_open: Optional[bool] = None) -> List[Bar]:
    """
    Fetch OHLCV bars for a single ticker.
    Uses FMP intraday when market is open (Ultimate plan), yfinance otherwise.
    """
    if market_open is None:
        market_open = is_market_open()

    if market_open:
        try:
            from data.fmp_client import get_intraday_bars
            raw  = get_intraday_bars(ticker, interval="1hour", days=90)
            bars = _fmp_bars_to_bar_list(raw)
            if len(bars) >= 30:
                log.debug("%s: %d hourly bars from FMP", ticker, len(bars))
                return bars
        except Exception as e:
            log.debug("%s: FMP intraday unavailable (%s)", ticker, e)
        bars = _yfinance_bars(ticker, market_open=True)
        log.debug("%s: %d hourly bars from yfinance", ticker, len(bars))
        return bars
    else:
        bars = _yfinance_bars(ticker, market_open=False)
        log.debug("%s: %d daily bars from yfinance", ticker, len(bars))
        return bars


def get_bars_batch(tickers: List[str], market_open: Optional[bool] = None) -> Dict[str, List[Bar]]:
    """
    Fetch bars for multiple tickers — ASYNC concurrent fetch (ENH-06).

    Uses ThreadPoolExecutor to run yfinance calls in parallel.
    600 tickers: ~75s sequential → ~12s with 40 workers.

    Falls back to sequential if async fails for any reason.
    """
    if market_open is None:
        market_open = is_market_open()

    if not tickers:
        return {}

    results: Dict[str, List[Bar]] = {}
    workers = min(_MAX_WORKERS, len(tickers))
    log.info("Fetching bars: %d tickers, %d workers (async)", len(tickers), workers)

    t0 = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_ticker = {
                executor.submit(get_bars, ticker, market_open): ticker
                for ticker in tickers
            }
            for future in as_completed(future_to_ticker):
                ticker = future_to_ticker[future]
                try:
                    results[ticker] = future.result(timeout=30)
                except Exception as e:
                    log.debug("%s: async fetch failed — %s", ticker, e)
                    results[ticker] = []
    except Exception as e:
        log.warning("Async fetch failed (%s) — falling back to sequential", e)
        delay = config.REQUEST_DELAY_MS / 1000.0
        for i, ticker in enumerate(tickers):
            results[ticker] = get_bars(ticker, market_open)
            if i < len(tickers) - 1:
                time.sleep(delay)

    elapsed = time.perf_counter() - t0
    fetched = sum(1 for bars in results.values() if bars)
    log.info("Bars fetched: %d/%d tickers in %.1fs (%.0f ms/ticker)",
             fetched, len(tickers), elapsed, elapsed / len(tickers) * 1000)
    return results
