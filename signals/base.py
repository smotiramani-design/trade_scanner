"""
signals/base.py — shared types used by every signal module.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Bias(str, Enum):
    BULL    = "bull"
    BEAR    = "bear"
    NEUTRAL = "neutral"


@dataclass
class SignalResult:
    name:   str
    bias:   Bias
    label:  str          # short human label, e.g. "Bullish engulfing"
    detail: str = ""     # optional one-liner of key values

    @property
    def icon(self) -> str:
        return {"bull": "▲", "bear": "▼", "neutral": "—"}[self.bias.value]

    def __str__(self) -> str:
        return f"[{self.icon} {self.bias.value.upper():7s}] {self.name}: {self.label}"


@dataclass
class TickerAnalysis:
    ticker:       str
    price:        float
    chg_pct:      float
    volume:       float
    bars:         int
    mode:         str                       # "Hourly" | "Daily"
    company_name: str = ""                  # e.g. "Apple Inc."
    signals:      List[SignalResult] = field(default_factory=list)
    fib:          Optional[object]   = field(default=None, repr=False)  # FibLevels | None
    atr_stop:     Optional[float]    = field(default=None, repr=False)  # ENH-10 ATR stop
    mtf_aligned:  bool               = field(default=True,  repr=False)  # ENH-16 MTF flag
    mtf_detail:   str                = field(default="",    repr=False)  # ENH-16 MTF detail
    earnings_soon:bool               = field(default=False, repr=False)  # ENH-11 earnings flag
    sector:        str               = field(default="",    repr=False)  # ENH-17 GICS sector
    gamma_data:    Optional[object]   = field(default=None, repr=False)  # ENH-20 Greeks/gamma

    @property
    def bull_count(self) -> int:
        return sum(1 for s in self.signals if s.bias == Bias.BULL)

    @property
    def bear_count(self) -> int:
        return sum(1 for s in self.signals if s.bias == Bias.BEAR)

    @property
    def net_score(self) -> int:
        return self.bull_count - self.bear_count

    @property
    def verdict(self) -> str:
        s = self.net_score
        if s >= 4:  return "Strong bullish"
        if s >= 2:  return "Moderately bullish"
        if s <= -4: return "Strong bearish"
        if s <= -2: return "Moderately bearish"
        return "Neutral"
