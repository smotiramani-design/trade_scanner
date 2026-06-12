"""
signals/vwap.py — ENH-12: VWAP (Volume-Weighted Average Price) signal.

VWAP is the primary intraday anchor used by institutional traders —
algorithms and desk traders benchmark every fill against VWAP.
Price above VWAP = institutions are net buyers. Below = net sellers.

Applicable sessions:
  Market open (hourly bars) — full intraday VWAP from day start
  Pre/after market          — rolling VWAP over available session bars

Not meaningful on daily bars — VWAP is an intraday concept.
For daily bar mode, returns NEUTRAL.

Bias logic:
  Price > VWAP by > threshold AND last 3 bars all above  → BULL
  Price < VWAP by > threshold AND last 3 bars all below  → BEAR
  Price crossing VWAP (flip in last 2 bars)              → signal direction of cross
  Close to VWAP (within threshold)                        → NEUTRAL

VWAP deviation bands (like Bollinger but volume-weighted):
  ±1 std dev band: normal range
  ±2 std dev band: extended / mean-reversion zone
"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

from data.yahoo_client import Bar
from signals.base import Bias, SignalResult

NAME = "VWAP"

VWAP_THRESHOLD_PCT = 0.3    # % distance from VWAP to trigger signal
BAND_MULTIPLIER    = 1.0    # std deviation band multiplier


def compute_vwap(bars: List[Bar]) -> Tuple[float, float, float]:
    """
    Compute VWAP and upper/lower standard deviation bands.

    Returns (vwap, upper_band, lower_band).
    VWAP = Σ(typical_price × volume) / Σ(volume)
    Bands = VWAP ± stddev of (typical_price − VWAP)
    """
    total_pv  = 0.0
    total_vol = 0.0
    sq_diffs  = []

    for bar in bars:
        typical = (bar.high + bar.low + bar.close) / 3
        vol     = bar.volume or 1  # avoid zero volume
        total_pv  += typical * vol
        total_vol += vol

    if total_vol <= 0:
        last = bars[-1].close if bars else 0
        return last, last, last

    vwap = total_pv / total_vol

    # Standard deviation of typical price vs VWAP (volume-weighted)
    total_sq = 0.0
    total_v2 = 0.0
    for bar in bars:
        typical = (bar.high + bar.low + bar.close) / 3
        vol     = bar.volume or 1
        total_sq += ((typical - vwap) ** 2) * vol
        total_v2 += vol

    std_dev = math.sqrt(total_sq / total_v2) if total_v2 > 0 else 0.0

    upper = round(vwap + BAND_MULTIPLIER * std_dev, 2)
    lower = round(vwap - BAND_MULTIPLIER * std_dev, 2)

    return round(vwap, 2), upper, lower


def analyze(bars: List[Bar], mode: str = "Daily") -> SignalResult:
    """
    Compute VWAP signal from OHLCV bars.

    Args:
        bars: OHLCV bars (hourly preferred; daily returns NEUTRAL)
        mode: "Hourly" | "Daily" — daily mode returns NEUTRAL
    """
    # VWAP is only meaningful for intraday sessions
    if mode == "Daily" or len(bars) < 10:
        return SignalResult(NAME, Bias.NEUTRAL,
                            "Intraday only" if mode == "Daily" else "Insufficient bars")

    # Use last session's bars only (today's bars) when in hourly mode
    # Heuristic: use last 8 bars (~1 trading day at hourly)
    session_bars = bars[-min(8, len(bars)):]

    vwap, upper, lower = compute_vwap(session_bars)
    if not vwap:
        return SignalResult(NAME, Bias.NEUTRAL, "VWAP unavailable")

    price     = bars[-1].close
    threshold = vwap * VWAP_THRESHOLD_PCT / 100
    deviation = price - vwap
    dev_pct   = deviation / vwap * 100

    detail = (f"VWAP=${vwap:.2f}  price=${price:.2f}  "
              f"dev={dev_pct:+.2f}%  "
              f"bands=[${lower:.2f}, ${upper:.2f}]")

    # Detect VWAP cross in last 2 bars
    if len(bars) >= 2:
        prev_price = bars[-2].close
        crossed_up   = prev_price < vwap and price > vwap
        crossed_down = prev_price > vwap and price < vwap
        if crossed_up:
            return SignalResult(NAME, Bias.BULL,
                                f"VWAP reclaim (${price:.2f} > ${vwap:.2f})", detail)
        if crossed_down:
            return SignalResult(NAME, Bias.BEAR,
                                f"VWAP breakdown (${price:.2f} < ${vwap:.2f})", detail)

    # Extended above upper band — overextended, mean-reversion risk
    if price > upper and price > vwap + threshold * 2:
        return SignalResult(NAME, Bias.NEUTRAL,
                            f"Extended above VWAP band (${upper:.2f})", detail)

    # Extended below lower band — oversold, potential bounce
    if price < lower and price < vwap - threshold * 2:
        return SignalResult(NAME, Bias.NEUTRAL,
                            f"Extended below VWAP band (${lower:.2f})", detail)

    # Standard above/below with threshold
    if price > vwap + threshold:
        # Check last 3 bars all above VWAP for confirmation
        last3_above = all(b.close > vwap for b in bars[-3:])
        if last3_above:
            return SignalResult(NAME, Bias.BULL,
                                f"Above VWAP ({dev_pct:+.2f}%)", detail)
        return SignalResult(NAME, Bias.NEUTRAL,
                            f"Above VWAP but inconsistent", detail)

    if price < vwap - threshold:
        last3_below = all(b.close < vwap for b in bars[-3:])
        if last3_below:
            return SignalResult(NAME, Bias.BEAR,
                                f"Below VWAP ({dev_pct:+.2f}%)", detail)
        return SignalResult(NAME, Bias.NEUTRAL,
                            f"Below VWAP but inconsistent", detail)

    return SignalResult(NAME, Bias.NEUTRAL,
                        f"Near VWAP (${vwap:.2f})", detail)
