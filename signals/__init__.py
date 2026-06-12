"""
signals/__init__.py — runs all 9 signals against a bar list.

Core signals (always run on OHLCV bars):
  candle, volume, sma, gaps, stochastics, cci, role_reversal

Extended signals (ENH-09, ENH-12):
  relative_strength — requires spy_bars kwarg
  vwap              — uses mode kwarg (Hourly/Daily)
"""
from typing import List, Optional

from data.yahoo_client import Bar
from signals.base import Bias, SignalResult, TickerAnalysis
from signals import candle, volume, sma, gaps, stochastics, cci, role_reversal
from signals import relative_strength, vwap as vwap_signal, news_sentiment

SIGNAL_MODULES = [candle, volume, sma, gaps, stochastics, cci, role_reversal]

# Single source of truth for all signal names
SIG_NAMES = [
    "Candle",    "Volume",  "SMA",    "Gaps",  "Stoch",
    "CCI",       "RR",      "Rel.Str","VWAP",  "News",
]


def run_all(
    bars:     List[Bar],
    spy_bars: Optional[List[Bar]] = None,
    mode:     str = "Daily",
    ticker:   str = "",
) -> List[SignalResult]:
    """Run all 10 signals. Core 7 on bars; 8=RS, 9=VWAP, 10=News."""
    results = [mod.analyze(bars) for mod in SIGNAL_MODULES]
    results.append(relative_strength.analyze(bars, spy_bars))
    results.append(vwap_signal.analyze(bars, mode))
    results.append(news_sentiment.analyze(ticker) if ticker else
                   SignalResult("News", Bias.NEUTRAL, "No ticker", ""))
    return results


__all__ = ["run_all", "Bias", "SignalResult", "TickerAnalysis",
           "SIGNAL_MODULES", "SIG_NAMES"]
