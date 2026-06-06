"""
signals/sma.py — Signal 3: 20-period SMA divergence.
"""
from typing import List
from data.yahoo_client import Bar
from signals.base import Bias, SignalResult

NAME = "20-day SMA divergence"


def _sma(values: List[float], n: int) -> List[float]:
    return [
        sum(values[i - n + 1 : i + 1]) / n if i >= n - 1 else float("nan")
        for i in range(len(values))
    ]


def analyze(bars: List[Bar]) -> SignalResult:
    if len(bars) < 22:
        return SignalResult(NAME, Bias.NEUTRAL, "Insufficient data")
    closes  = [b.close for b in bars]
    sma_val = _sma(closes, 20)[-1]
    last    = closes[-1]
    pct     = (last - sma_val) / sma_val * 100

    bias  = Bias.BULL if pct > 0 else Bias.BEAR
    wide  = abs(pct) > 5
    label = f"Wide divergence {'above' if pct > 0 else 'below'} SMA" if wide else \
            f"Near 20-period SMA ({'above' if pct > 0 else 'below'})"
    detail = f"Close ${last:.2f} · SMA ${sma_val:.2f} · {'+' if pct > 0 else ''}{pct:.1f}%"
    return SignalResult(NAME, bias, label, detail)
