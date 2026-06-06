"""
signals/stochastics.py — Signal 5: Stochastic oscillator (%K / %D).
Default: 14-period %K, 3-period %D smoothing.
"""
from typing import List, Tuple
from data.yahoo_client import Bar
from signals.base import Bias, SignalResult

NAME = "Stochastics"


def _stoch(bars: List[Bar], k_period: int = 14, d_period: int = 3) -> Tuple[float, float]:
    k_vals = []
    for i in range(len(bars)):
        if i < k_period - 1:
            continue
        sl  = bars[i - k_period + 1 : i + 1]
        lo  = min(b.low  for b in sl)
        hi  = max(b.high for b in sl)
        k   = 50.0 if hi == lo else (bars[i].close - lo) / (hi - lo) * 100
        k_vals.append(k)
    if len(k_vals) < d_period:
        return float("nan"), float("nan")
    k = k_vals[-1]
    d = sum(k_vals[-d_period:]) / d_period
    return k, d


def analyze(bars: List[Bar]) -> SignalResult:
    if len(bars) < 20:
        return SignalResult(NAME, Bias.NEUTRAL, "Insufficient data")
    k, d = _stoch(bars)
    if k != k:
        return SignalResult(NAME, Bias.NEUTRAL, "Insufficient data")

    kv, dv = round(k, 1), round(d, 1)
    spread = abs(kv - dv)
    wide   = spread > 15

    if kv >= 80:
        label = "Overbought" + (" · Wide divergence" if wide else "")
        bias  = Bias.BEAR
    elif kv <= 20:
        label = "Oversold" + (" · Wide divergence" if wide else "")
        bias  = Bias.BULL
    elif kv > dv:
        label = "%K above %D (bullish cross)" + (" · Wide" if wide else "")
        bias  = Bias.BULL
    else:
        label = "%K below %D (bearish cross)" + (" · Wide" if wide else "")
        bias  = Bias.BEAR

    detail = f"%K {kv} · %D {dv} · Spread {spread:.1f}"
    return SignalResult(NAME, bias, label, detail)
