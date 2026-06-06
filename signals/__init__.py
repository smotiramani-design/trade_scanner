"""
signals/__init__.py — runs all 7 signals against a bar list.
"""
from typing import List

from data.yahoo_client import Bar
from signals.base import Bias, SignalResult, TickerAnalysis
from signals import candle, volume, sma, gaps, stochastics, cci, role_reversal

SIGNAL_MODULES = [candle, volume, sma, gaps, stochastics, cci, role_reversal]


def run_all(bars: List[Bar]) -> List[SignalResult]:
    """Run all 7 signal modules and return results in order."""
    return [mod.analyze(bars) for mod in SIGNAL_MODULES]


__all__ = ["run_all", "Bias", "SignalResult", "TickerAnalysis", "SIGNAL_MODULES"]
