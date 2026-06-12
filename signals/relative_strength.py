"""
signals/relative_strength.py — ENH-09: Relative Strength vs SPY.

Compares a stock's recent price performance to the S&P 500 (SPY) over
the same period. A stock moving up while SPY is flat or down has genuine
momentum — not just beta riding a bull market.

Formula:
  RS_score = stock_return_N_bars − spy_return_N_bars
  Periods:  5-bar, 10-bar, 20-bar (multi-period confirmation)

Bias logic:
  RS > +1.5% over both 5b and 10b  → BULL (outperforming market)
  RS < −1.5% over both 5b and 10b  → BEAR (underperforming market)
  Mixed / flat                       → NEUTRAL

SPY bars are fetched once per scan run and cached. The scan passes
the SPY bar list to analyze() alongside the ticker's own bars.

Usage in scanner.py:
    spy_bars = get_bars("SPY", mkt_open)
    rs_result = analyze(bars, spy_bars)
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from data.yahoo_client import Bar
from signals.base import Bias, SignalResult

NAME = "Rel. Strength"

# Thresholds (percentage points of outperformance)
RS_STRONG   =  2.0   # >+2% outperformance over 10 bars → BULL
RS_WEAK     = -2.0   # <-2% underperformance            → BEAR
RS_MODERATE =  1.0   # +1% threshold for 5-bar period


def _period_return(bars: List[Bar], lookback: int) -> float:
    """Return % price change over the last N bars."""
    if len(bars) < lookback + 1:
        return 0.0
    start = bars[-lookback - 1].close
    end   = bars[-1].close
    if not start:
        return 0.0
    return (end - start) / start * 100


def _rs_score(
    ticker_bars: List[Bar],
    spy_bars:    List[Bar],
    period:      int,
) -> float:
    """Relative return vs SPY over N bars (+ = outperforming, - = lagging)."""
    ticker_ret = _period_return(ticker_bars, period)
    spy_ret    = _period_return(spy_bars,    period)
    return round(ticker_ret - spy_ret, 3)


def analyze(
    bars:     List[Bar],
    spy_bars: Optional[List[Bar]] = None,
) -> SignalResult:
    """
    Compute Relative Strength vs SPY.

    Args:
        bars:     ticker OHLCV bars
        spy_bars: SPY bars fetched from same session (optional)
                  If None, returns NEUTRAL — signal requires SPY data.
    """
    if spy_bars is None or len(spy_bars) < 21 or len(bars) < 21:
        return SignalResult(
            NAME, Bias.NEUTRAL,
            "No SPY data" if spy_bars is None else "Insufficient bars",
            "",
        )

    rs5  = _rs_score(bars, spy_bars,  5)
    rs10 = _rs_score(bars, spy_bars, 10)
    rs20 = _rs_score(bars, spy_bars, 20)

    detail = (f"vs SPY — 5b:{rs5:+.1f}%  10b:{rs10:+.1f}%  20b:{rs20:+.1f}%")

    # Need multi-period confirmation — both 5-bar and 10-bar agree
    bull_5  = rs5  >  RS_MODERATE
    bull_10 = rs10 >  RS_STRONG
    bear_5  = rs5  <  -RS_MODERATE
    bear_10 = rs10 <  RS_WEAK

    if bull_5 and bull_10:
        strength = "strongly" if rs10 > RS_STRONG * 1.5 else "moderately"
        return SignalResult(
            NAME, Bias.BULL,
            f"Outperforming SPY {strength} ({rs10:+.1f}% 10-bar)",
            detail,
        )

    if bear_5 and bear_10:
        strength = "strongly" if rs10 < RS_WEAK * 1.5 else "moderately"
        return SignalResult(
            NAME, Bias.BEAR,
            f"Underperforming SPY {strength} ({rs10:+.1f}% 10-bar)",
            detail,
        )

    # Mixed signals
    if rs5 > RS_MODERATE and rs10 < 0:
        return SignalResult(NAME, Bias.NEUTRAL,
                            "Short-term bounce, weak medium-term RS", detail)
    if rs5 < -RS_MODERATE and rs10 > 0:
        return SignalResult(NAME, Bias.NEUTRAL,
                            "Short-term pullback, medium-term RS intact", detail)

    return SignalResult(NAME, Bias.NEUTRAL, "In line with market", detail)
