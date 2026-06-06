"""
signals/cci.py — Signal 6: Commodity Channel Index (20-period).
Overbought > +100, Oversold < -100, zero-line crossings noted.
"""
from typing import List, Tuple
from data.yahoo_client import Bar
from signals.base import Bias, SignalResult

NAME = "CCI"


def _cci_series(bars: List[Bar], period: int = 20) -> List[float]:
    results = []
    for i in range(len(bars)):
        if i < period - 1:
            continue
        sl = bars[i - period + 1 : i + 1]
        tp = [(b.high + b.low + b.close) / 3 for b in sl]
        mean = sum(tp) / period
        md   = sum(abs(v - mean) for v in tp) / period
        results.append((tp[-1] - mean) / (0.015 * md) if md else 0.0)
    return results


def analyze(bars: List[Bar]) -> SignalResult:
    if len(bars) < 22:
        return SignalResult(NAME, Bias.NEUTRAL, "Insufficient data")
    series = _cci_series(bars)
    if len(series) < 2:
        return SignalResult(NAME, Bias.NEUTRAL, "Insufficient data")
    cur, prv = series[-1], series[-2]

    if cur > 100:
        label = "Overbought (> +100)"
        bias  = Bias.BEAR
    elif cur < -100:
        label = "Oversold (< -100)"
        bias  = Bias.BULL
    else:
        label = "Bullish zone" if cur > 0 else "Bearish zone"
        bias  = Bias.BULL if cur > 0 else Bias.BEAR

    if prv < 0 <= cur:
        label += " · Zero-line cross ↑"
        bias   = Bias.BULL
    elif prv > 0 >= cur:
        label += " · Zero-line cross ↓"
        bias   = Bias.BEAR

    detail = f"CCI {cur:.1f} · Prev {prv:.1f} · {'Rising' if cur > prv else 'Falling'}"
    return SignalResult(NAME, bias, label, detail)
