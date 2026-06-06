"""
signals/volume.py — Signal 2: Volume vs 20-bar trend.
"""
from typing import List
from data.yahoo_client import Bar
from signals.base import Bias, SignalResult

NAME = "Volume"


def analyze(bars: List[Bar]) -> SignalResult:
    if len(bars) < 22:
        return SignalResult(NAME, Bias.NEUTRAL, "Insufficient data")
    cur  = bars[-1]
    avg  = sum(b.volume for b in bars[-21:-1]) / 20
    if avg == 0:
        return SignalResult(NAME, Bias.NEUTRAL, "Zero avg volume")
    ratio = cur.volume / avg
    is_b  = cur.close >= cur.open

    if ratio > 1.5:
        label  = "Significantly above trend"
        bias   = Bias.BULL if is_b else Bias.BEAR
    elif ratio > 1.1:
        label  = "Above trend"
        bias   = Bias.BULL if is_b else Bias.BEAR
    elif ratio < 0.7:
        label  = "Significantly below trend"
        bias   = Bias.NEUTRAL
    else:
        label  = "In line with trend"
        bias   = Bias.NEUTRAL

    detail = f"{ratio*100:.0f}% of 20-bar avg · {'Up' if is_b else 'Down'} bar"
    return SignalResult(NAME, bias, label, detail)
