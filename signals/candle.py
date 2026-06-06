"""
signals/candle.py — Signal 1: Candlestick pattern detection.

Patterns detected:
  Bullish: engulfing, harami, hammer, inverted hammer, stale red reversal
  Bearish: engulfing, harami, shooting star, hanging man, stale green exhaustion
"""
from typing import List

from data.yahoo_client import Bar
from signals.base import Bias, SignalResult

NAME = "Candle pattern"


def analyze(bars: List[Bar]) -> SignalResult:
    if len(bars) < 3:
        return SignalResult(NAME, Bias.NEUTRAL, "Insufficient data")

    b   = bars[-1]   # current
    p   = bars[-2]   # previous
    pp  = bars[-3]   # two back

    body = abs(b.close - b.open)
    rng  = b.high - b.low or 1e-9
    uw   = b.high - max(b.close, b.open)   # upper wick
    lw   = min(b.close, b.open) - b.low    # lower wick
    pb   = abs(p.close - p.open)           # prev body
    is_b  = b.close > b.open
    p_is_b = p.close > p.open

    detail = f"O:{b.open:.2f} H:{b.high:.2f} L:{b.low:.2f} C:{b.close:.2f}"

    if not p_is_b and is_b and b.open < p.close and b.close > p.open:
        return SignalResult(NAME, Bias.BULL, "Bullish engulfing", detail)

    if p_is_b and not is_b and b.open > p.close and b.close < p.open:
        return SignalResult(NAME, Bias.BEAR, "Bearish engulfing", detail)

    if not p_is_b and is_b and body < pb * 0.5 and b.open > p.low and b.close < p.open:
        return SignalResult(NAME, Bias.BULL, "Bullish harami", detail)

    if p_is_b and not is_b and body < pb * 0.5 and b.open < p.high and b.close > p.open:
        return SignalResult(NAME, Bias.BEAR, "Bearish harami", detail)

    if lw >= 2 * body and uw < body and is_b:
        return SignalResult(NAME, Bias.BULL, "Hammer", detail)

    if uw >= 2 * body and lw < body and not is_b:
        return SignalResult(NAME, Bias.BEAR, "Shooting star", detail)

    if lw >= 2 * body and uw < body and not is_b:
        return SignalResult(NAME, Bias.BEAR, "Hanging man", detail)

    if uw >= 2 * body and lw < body and is_b:
        return SignalResult(NAME, Bias.BULL, "Inverted hammer", detail)

    all_up   = pp.close > pp.open and p.close > p.open and b.close > b.open
    all_down = not (pp.close > pp.open) and not (p.close > p.open) and not (b.close > b.open)
    if all_up:
        return SignalResult(NAME, Bias.BEAR, "Stale green (3-bar exhaustion)", detail)
    if all_down:
        return SignalResult(NAME, Bias.BULL, "Stale red (3-bar reversal)", detail)

    bias = Bias.BULL if is_b else Bias.BEAR
    label = "Bullish bar" if is_b else "Bearish bar"
    return SignalResult(NAME, bias, label, detail)
