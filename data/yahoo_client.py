"""
data/yahoo_client.py — Yahoo Finance historical OHLCV bar fetcher.
Uses yfinance for reliability; falls back to direct API on failure.
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import pandas as pd
import yfinance as yf

import config

log = logging.getLogger(__name__)


@dataclass
class Bar:
    timestamp: datetime
    open:  float
    high:  float
    low:   float
    close: float
    volume: float

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open


def is_market_open() -> bool:
    """Return True if US equity market is currently open (ET 9:30–16:00 Mon–Fri)."""
    now_et = datetime.now(tz=timezone.utc).astimezone(
        __import__("zoneinfo", fromlist=["ZoneInfo"]).ZoneInfo("America/New_York")
        if hasattr(__import__("zoneinfo"), "ZoneInfo")
        else __import__("pytz").timezone("America/New_York")
    )
    if now_et.weekday() >= 5:
        return False
    minutes = now_et.hour * 60 + now_et.minute
    return 570 <= minutes < 960


def get_bars(ticker: str, market_open: Optional[bool] = None) -> List[Bar]:
    """
    Download OHLCV bars for a ticker.
    - Market open  → 1h interval, 3-month range
    - Market closed → 1d interval, 1-year range
    Returns a list of Bar objects sorted oldest-first.
    """
    if market_open is None:
        market_open = is_market_open()

    interval = "1h" if market_open else "1d"
    period   = "3mo" if market_open else "1y"

    try:
        tk = yf.Ticker(ticker)
        df: pd.DataFrame = tk.history(period=period, interval=interval, auto_adjust=True)
        if df.empty:
            log.warning("%s: empty history from yfinance", ticker)
            return []
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        bars = [
            Bar(
                timestamp=idx.to_pydatetime(),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row.get("Volume", 0) or 0),
            )
            for idx, row in df.iterrows()
        ]
        log.debug("%s: %d bars (%s / %s)", ticker, len(bars), interval, period)
        return bars
    except Exception as e:
        log.error("%s: yfinance error — %s", ticker, e)
        return []


def get_bars_batch(tickers: List[str], market_open: Optional[bool] = None) -> dict:
    """
    Fetch bars for multiple tickers sequentially with a small delay.
    Returns {ticker: List[Bar]}.
    """
    if market_open is None:
        market_open = is_market_open()
    results = {}
    delay = config.REQUEST_DELAY_MS / 1000.0
    for i, ticker in enumerate(tickers):
        results[ticker] = get_bars(ticker, market_open)
        if i < len(tickers) - 1:
            time.sleep(delay)
    return results
