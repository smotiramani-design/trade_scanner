"""
signals/atr.py — ATR stop + ATR R-multiple trade plan.

Average True Range (ATR) measures a stock's actual volatility.
A fixed 2% stop is arbitrary — too tight for NVDA, too wide for AAPL.
ATR-based levels adapt automatically.

ATR plan (parallel to Fibonacci — does NOT replace Fib):
  Entry  = scan price (market-style at signal time)
  Stop   = entry ± (multiplier × ATR)     [1.5× default]
  R      = |entry − stop|
  T1     = entry ± 1R                     [1:1 reward]
  T2     = entry ± 2R                     [1:2 reward]

The ATR stop is also used in trade_engine.py to widen a Fib stop when ATR
implies more room than the Fib invalidation level.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from data.yahoo_client import Bar


ATR_PERIOD:     int   = 14
ATR_MULTIPLIER: float = 1.5    # 1.5× ATR = institutional standard


@dataclass
class AtrPlan:
    """Volatility trade plan in R-multiples (alongside FibLevels)."""
    entry:      float
    stop:       float
    target_1:   float          # 1R
    target_2:   float          # 2R
    atr:        float          # raw ATR(14) in price units
    r_distance: float          # |entry − stop|
    multiplier: float
    direction:  str            # "bullish" | "bearish"


def compute_atr(bars: List[Bar], period: int = ATR_PERIOD) -> float:
    """
    Compute ATR using Wilder's smoothed average.
    Returns ATR as an absolute price value (e.g. 3.42 for a $200 stock).
    Returns 0.0 if insufficient bars.
    """
    if len(bars) < period + 1:
        return 0.0

    trs: List[float] = []
    for i in range(1, len(bars)):
        high = bars[i].high
        low = bars[i].low
        prev_close = bars[i - 1].close
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        trs.append(tr)

    if not trs:
        return 0.0

    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period

    return round(atr, 4)


def compute_atr_stop(
    bars:       List[Bar],
    price:      float,
    net_score:  int,
    multiplier: float = ATR_MULTIPLIER,
    period:     int   = ATR_PERIOD,
    direction:  Optional[str] = None,
) -> Optional[float]:
    """
    Compute ATR-based stop loss price (legacy helper).

    Prefer `compute_atr_plan` for the full Entry / Stop / T1 / T2 plan.
    Prefer `direction` ("bullish"|"bearish"|"neutral") when available.
    """
    plan = compute_atr_plan(
        bars, price, net_score,
        multiplier=multiplier, period=period, direction=direction,
    )
    return plan.stop if plan else None


def compute_atr_plan(
    bars:       List[Bar],
    price:      float,
    net_score:  int,
    multiplier: float = ATR_MULTIPLIER,
    period:     int   = ATR_PERIOD,
    direction:  Optional[str] = None,
) -> Optional[AtrPlan]:
    """
    Full ATR R-multiple plan: entry (= price), stop (1.5×ATR), T1 (1R), T2 (2R).

    Direction follows weighted conviction when provided (same as Fib / picks).
    Returns None for neutral or when ATR cannot be computed.
    """
    if not price or price <= 0:
        return None

    if direction not in ("bullish", "bearish", "neutral"):
        if net_score == 0:
            return None
        direction = "bullish" if net_score > 0 else "bearish"
    if direction == "neutral":
        return None

    atr = compute_atr(bars, period)
    if atr <= 0:
        return None

    r = round(multiplier * atr, 4)
    if r <= 0:
        return None

    entry = round(float(price), 2)
    if direction == "bullish":
        stop = round(entry - r, 2)
        t1 = round(entry + r, 2)
        t2 = round(entry + 2.0 * r, 2)
    else:
        stop = round(entry + r, 2)
        t1 = round(entry - r, 2)
        t2 = round(entry - 2.0 * r, 2)

    return AtrPlan(
        entry=entry,
        stop=stop,
        target_1=t1,
        target_2=t2,
        atr=atr,
        r_distance=round(r, 2),
        multiplier=multiplier,
        direction=direction,
    )


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
    pct = atr / price * 100
    stop = atr * ATR_MULTIPLIER
    return (f"ATR(14)=${atr:.2f} ({pct:.1f}%)  "
            f"1.5× stop=${stop:.2f} ({pct*ATR_MULTIPLIER:.1f}%)")
