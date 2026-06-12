"""
signals/gaps.py — Signal 4: Open gap detection (above / below market).

A gap occurs when a bar opens above the prior bar's high (gap-up) or
below the prior bar's low (gap-down). The gap is "open" (unfilled) if
no subsequent bar has traded back into the gap zone.

Gap direction relative to current price:
  gap-up   creates gap zone [prev.high, curr.low]
            → gap is BELOW price when curr.low < current_price  (bullish support)
            → gap is ABOVE price when prev.high > current_price (bearish resistance)

  gap-down creates gap zone [curr.high, prev.low]
            → gap is ABOVE price when curr.high > current_price (bearish resistance)
            → gap is BELOW price when prev.low  < current_price (bullish support)

Bias:
  Open gap(s) ABOVE price → resistance → BEAR
  Open gap(s) BELOW price → support    → BULL
  Both sides              → NEUTRAL
  None                    → NEUTRAL

Bugs fixed vs original:
  1. Range extended to len(bars) — original stopped at len-1, silently missing
     any gap on the most recent bar (today's opening gap-up or gap-down).
  2. Filter conditions corrected — original used wrong field to classify whether
     a gap is above or below current price, causing the latest-bar gaps to be
     dropped even after fix #1.
  3. Gaps sorted by proximity — original returned chronological order, so the
     nearest gap was not necessarily first.
"""
from typing import List, Tuple
from data.yahoo_client import Bar
from signals.base import Bias, SignalResult

NAME = "Gaps"


def _find_open_gaps(bars: List[Bar]) -> Tuple[List[Tuple], List[Tuple]]:
    """
    Scan all bars for unfilled gaps relative to current price.

    Returns:
      gaps_above: [(gap_bottom, gap_top), ...] sorted nearest-first (ascending bottom)
      gaps_below: [(gap_bottom, gap_top), ...] sorted nearest-first (descending top)
    """
    last_close = bars[-1].close
    gaps_above: List[Tuple[float, float]] = []
    gaps_below: List[Tuple[float, float]] = []

    for i in range(1, len(bars)):          # includes the final bar
        prev = bars[i - 1]
        curr = bars[i]

        # ── Gap-up: curr opened above prev's high ────────────────────────────
        if curr.low > prev.high:
            gap_bottom = prev.high
            gap_top    = curr.low
            filled = any(b.low <= gap_bottom for b in bars[i + 1:])
            if not filled:
                # Gap is below current price → bullish magnet / support
                if gap_top < last_close:
                    gaps_below.append((gap_bottom, gap_top))
                # Gap is above current price → bearish resistance
                elif gap_bottom > last_close:
                    gaps_above.append((gap_bottom, gap_top))

        # ── Gap-down: curr opened below prev's low ───────────────────────────
        if curr.high < prev.low:
            gap_bottom = curr.high
            gap_top    = prev.low
            filled = any(b.high >= gap_top for b in bars[i + 1:])
            if not filled:
                # Gap is above current price → bearish resistance
                if gap_bottom > last_close:
                    gaps_above.append((gap_bottom, gap_top))
                # Gap is below current price → bullish support
                elif gap_top < last_close:
                    gaps_below.append((gap_bottom, gap_top))

    # Sort by proximity to current price
    gaps_above.sort(key=lambda g: g[0])           # smallest bottom = nearest above
    gaps_below.sort(key=lambda g: g[1], reverse=True)  # largest top = nearest below

    return gaps_above, gaps_below


def analyze(bars: List[Bar]) -> SignalResult:
    if len(bars) < 10:
        return SignalResult(NAME, Bias.NEUTRAL, "Insufficient data")

    above, below = _find_open_gaps(bars)

    if above and below:
        detail = (
            f"{len(above)} above (nearest ${above[0][0]:.2f}–${above[0][1]:.2f}) · "
            f"{len(below)} below (nearest ${below[0][1]:.2f}–${below[0][0]:.2f})"
        )
        return SignalResult(NAME, Bias.NEUTRAL, "Open gaps above and below", detail)

    if above:
        nearest = above[0]
        detail  = f"Nearest: ${nearest[0]:.2f}–${nearest[1]:.2f}"
        if len(above) > 1:
            detail += f" (+{len(above)-1} more)"
        return SignalResult(NAME, Bias.BEAR,
                            f"{len(above)} open gap(s) above (resistance)", detail)

    if below:
        nearest = below[0]
        detail  = f"Nearest: ${nearest[1]:.2f}–${nearest[0]:.2f}"
        if len(below) > 1:
            detail += f" (+{len(below)-1} more)"
        return SignalResult(NAME, Bias.BULL,
                            f"{len(below)} open gap(s) below (support)", detail)

    return SignalResult(NAME, Bias.NEUTRAL, "No open gaps nearby", "Clean price area")
