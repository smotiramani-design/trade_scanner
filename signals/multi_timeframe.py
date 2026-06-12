"""
signals/multi_timeframe.py — ENH-16: Multi-timeframe confirmation.

Eliminates false positives by requiring the daily trend to agree with
the hourly signal direction before flagging a setup as high-quality.

Logic:
  Hourly signal  — net_score from 7-signal model on hourly bars
  Daily signal   — same 7-signal model applied to daily bars
  Aligned        — both agree on direction (both BULL or both BEAR)
  Conflicting    — hourly BULL but daily BEAR (or vice versa) → penalise

The alignment result is stored on TickerAnalysis.mtf_aligned (bool) and
TickerAnalysis.mtf_detail (str) and is used in conviction.py to apply
a penalty to the conviction % when timeframes conflict.

In daily-bar mode (scanner running outside market hours), mtf_aligned
is set to True by default — the check only applies during market hours
when hourly bars are used as the primary signal source.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from data.yahoo_client import Bar
from signals import run_all
from signals.base import Bias


def _net_score(bars: List[Bar]) -> int:
    """Run all 10 signals and return net score. Returns 0 if insufficient bars."""
    if len(bars) < 30:
        return 0
    sigs = run_all(bars)
    bull = sum(1 for s in sigs if s.bias == Bias.BULL)
    bear = sum(1 for s in sigs if s.bias == Bias.BEAR)
    return bull - bear


def check_alignment(
    hourly_bars:   List[Bar],
    daily_bars:    List[Bar],
    hourly_score:  int,
) -> Tuple[bool, str]:
    """
    Check whether the daily trend confirms the hourly signal.

    Args:
        hourly_bars:  hourly OHLCV bars (already computed by scanner)
        daily_bars:   daily OHLCV bars fetched for the same ticker
        hourly_score: net_score from the hourly signal run (saves recomputing)

    Returns:
        (aligned: bool, detail: str)
        aligned=True  → timeframes agree, setup is higher quality
        aligned=False → timeframes conflict, apply conviction penalty
    """
    if len(daily_bars) < 30:
        return True, "No daily bars (MTF skipped)"

    daily_score = _net_score(daily_bars)

    hourly_dir = ("bull" if hourly_score > 0 else
                  "bear" if hourly_score < 0 else "neutral")
    daily_dir  = ("bull" if daily_score  > 0 else
                  "bear" if daily_score  < 0 else "neutral")

    detail = (f"Hourly: {hourly_dir} ({hourly_score:+d})  "
              f"Daily: {daily_dir} ({daily_score:+d})")

    # Neutral on either timeframe → don't penalise but note it
    if hourly_dir == "neutral" or daily_dir == "neutral":
        return True, f"MTF: one timeframe neutral — {detail}"

    # Both same direction → aligned
    if hourly_dir == daily_dir:
        return True, f"MTF aligned ✓ — {detail}"

    # Opposing directions → not aligned
    return False, f"MTF conflict ✗ — {detail}"


def mtf_conviction_multiplier(aligned: bool) -> float:
    """
    Return a multiplier (0.0–1.0) to apply to conviction % when MTF conflicts.
    Aligned: 1.0 (no penalty)
    Conflicting: 0.7 (30% reduction in conviction)
    """
    return 1.0 if aligned else 0.7
