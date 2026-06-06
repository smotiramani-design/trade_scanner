"""
signals/gaps.py — Signal 4: Open gap detection (above / below market).
"""
from typing import List, Optional, Tuple
from data.yahoo_client import Bar
from signals.base import Bias, SignalResult

NAME = "Gaps"


def _find_open_gaps(bars: List[Bar]) -> Tuple[List[Tuple], List[Tuple]]:
    """Returns (gaps_above, gaps_below) relative to last close."""
    last_close = bars[-1].close
    gaps_above, gaps_below = [], []
    for i in range(1, len(bars) - 1):
        gap_up   = bars[i].low  > bars[i - 1].high
        gap_down = bars[i].high < bars[i - 1].low
        if gap_up:
            filled = any(b.low <= bars[i - 1].high for b in bars[i + 1 :])
            if not filled and bars[i].low > last_close:
                gaps_above.append((bars[i - 1].high, bars[i].low))
        if gap_down:
            filled = any(b.high >= bars[i - 1].low for b in bars[i + 1 :])
            if not filled and bars[i].high < last_close:
                gaps_below.append((bars[i].high, bars[i - 1].low))
    return gaps_above, gaps_below


def analyze(bars: List[Bar]) -> SignalResult:
    if len(bars) < 10:
        return SignalResult(NAME, Bias.NEUTRAL, "Insufficient data")
    above, below = _find_open_gaps(bars)
    if above and below:
        detail = f"Above ${above[0][0]:.2f} · Below ${below[0][1]:.2f}"
        return SignalResult(NAME, Bias.NEUTRAL, "Open gaps above and below", detail)
    if above:
        detail = f"Nearest gap: ${above[0][0]:.2f}–${above[0][1]:.2f}"
        return SignalResult(NAME, Bias.BEAR, f"{len(above)} open gap(s) above (resistance)", detail)
    if below:
        detail = f"Nearest gap: ${below[0][0]:.2f}–${below[0][1]:.2f}"
        return SignalResult(NAME, Bias.BULL, f"{len(below)} open gap(s) below (support)", detail)
    return SignalResult(NAME, Bias.NEUTRAL, "No open gaps nearby", "Clean price area")
