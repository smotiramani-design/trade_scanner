"""
signals/role_reversal.py — Signal 7: Role reversal (S/R level flip).
Checks whether price is testing a prior high/low that has become
support or resistance, and whether 20-SMA is acting as S/R.
"""
from typing import List
from data.yahoo_client import Bar
from signals.base import Bias, SignalResult

NAME = "Role reversal"
_PROXIMITY = 0.02   # within 2% counts as "testing"


def _sma(closes: List[float], n: int) -> float:
    if len(closes) < n:
        return float("nan")
    return sum(closes[-n:]) / n


def analyze(bars: List[Bar]) -> SignalResult:
    if len(bars) < 30:
        return SignalResult(NAME, Bias.NEUTRAL, "Insufficient data")

    closes  = [b.close for b in bars]
    last    = closes[-1]
    sma20   = _sma(closes, 20)

    recent_hi  = max(b.high  for b in bars[-20:])
    recent_lo  = min(b.low   for b in bars[-20:])
    prior_hi   = max(b.high  for b in bars[-40:-20]) if len(bars) >= 40 else recent_hi
    prior_lo   = min(b.low   for b in bars[-40:-20]) if len(bars) >= 40 else recent_lo

    near_prior_hi = abs(last - prior_hi) / prior_hi < _PROXIMITY
    near_prior_lo = abs(last - prior_lo) / prior_lo < _PROXIMITY

    if near_prior_hi:
        bias   = Bias.BULL if last > prior_hi else Bias.BEAR
        label  = "Breakout above prior resistance" if last > prior_hi else "Rejection at prior resistance"
        detail = f"Prior high ${prior_hi:.2f} · Now ${last:.2f}"
        return SignalResult(NAME, bias, label, detail)

    if near_prior_lo:
        bias   = Bias.BULL if last > prior_lo else Bias.BEAR
        label  = "Bounce off prior support" if last > prior_lo else "Break below prior support"
        detail = f"Prior low ${prior_lo:.2f} · Now ${last:.2f}"
        return SignalResult(NAME, bias, label, detail)

    pct    = (last - sma20) / sma20 * 100 if sma20 == sma20 else 0
    bias   = Bias.BULL if last > sma20 else Bias.BEAR
    label  = "Above SMA (acting as support)" if last > sma20 else "Below SMA (acting as resistance)"
    detail = f"SMA20 ${sma20:.2f} · Close ${last:.2f} · {'+' if pct>=0 else ''}{pct:.1f}%"
    return SignalResult(NAME, bias, label, detail)
