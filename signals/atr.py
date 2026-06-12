"""
signals/atr.py — ENH-10: ATR-based dynamic stop loss.

Average True Range (ATR) measures a stock's actual daily volatility.
A fixed 2% stop is arbitrary — it's too tight for NVDA (ATR ~3.5%) and
too wide for AAPL (ATR ~1.2%). ATR-based stops adapt automatically.

Formula:
  True Range  = max(high-low, |high-prev_close|, |low-prev_close|)
  ATR(14)     = 14-period Wilder's smoothed average of True Range
  ATR stop    = entry_price - (ATR_multiplier × ATR)   [longs]
              = entry_price + (ATR_multiplier × ATR)   [shorts]

Multiplier of 1.5× is standard institutional practice:
  Tight  = 1.0×  (aggressive, more false stops)
  Normal = 1.5×  (balanced — default)
  Wide   = 2.0×  (conservative, larger risk per trade)

The ATR stop is stored on TickerAnalysis.atr_stop and used in
trade_engine.py as the stop level when it results in a better
(wider) stop than the Fibonacci or fixed % level.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from data.yahoo_client import Bar


ATR_PERIOD:     int   = 14
ATR_MULTIPLIER: float = 1.5    # 1.5× ATR = institutional standard


def compute_atr(bars: List[Bar], period: int = ATR_PERIOD) -> float:
    """
    Compute ATR using Wilder's smoothed average.
    Returns ATR as an absolute price value (e.g. 3.42 for a $200 stock).
    Returns 0.0 if insufficient bars.
    """
    if len(bars) < period + 1:
        return 0.0

    # True range for each bar
    trs: List[float] = []
    for i in range(1, len(bars)):
        high      = bars[i].high
        low       = bars[i].low
        prev_close = bars[i - 1].close
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low  - prev_close),
        )
        trs.append(tr)

    if not trs:
        return 0.0

    # Initial ATR = simple average of first `period` TRs
    atr = sum(trs[:period]) / period

    # Wilder's smoothing for remaining bars
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period

    return round(atr, 4)


def compute_atr_stop(
    bars:       List[Bar],
    price:      float,
    net_score:  int,
    multiplier: float = ATR_MULTIPLIER,
    period:     int   = ATR_PERIOD,
) -> Optional[float]:
    """
    Compute ATR-based stop loss price.

    Returns the stop price (not distance), or None if ATR cannot be computed.

    For longs  (net_score > 0): stop = price - (multiplier × ATR)
    For shorts (net_score < 0): stop = price + (multiplier × ATR)
    Neutral:                    returns None
    """
    if not price or price <= 0 or net_score == 0:
        return None

    atr = compute_atr(bars, period)
    if atr <= 0:
        return None

    stop_distance = multiplier * atr

    if net_score > 0:
        stop = round(price - stop_distance, 2)
    else:
        stop = round(price + stop_distance, 2)

    return stop


def atr_stop_pct(bars: List[Bar], price: float, multiplier: float = ATR_MULTIPLIER) -> float:
    """Return ATR stop distance as a percentage of price. Useful for display."""
    atr = compute_atr(bars)
    if not atr or not price:
        return 0.0
    return round(multiplier * atr / price * 100, 2)


def atr_signal_detail(bars: List[Bar], price: float) -> str:
    """Return human-readable ATR detail string for email/terminal output."""
    atr = compute_atr(bars)
    if not atr or not price:
        return "ATR unavailable"
    pct  = atr / price * 100
    stop = atr * ATR_MULTIPLIER
    return (f"ATR(14)=${atr:.2f} ({pct:.1f}%)  "
            f"1.5× stop=${stop:.2f} ({pct*ATR_MULTIPLIER:.1f}%)")
