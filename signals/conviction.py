"""
signals/conviction.py — conviction scoring and analysis commentary.

Conviction goes beyond the raw net score by weighting signals
that tend to have higher predictive value and penalizing
conflicting or low-quality setups.

Weights per signal (index matches SIGNAL_MODULES order):
  0  Candle pattern   — 1.5x  (primary entry trigger)
  1  Volume           — 1.5x  (confirms intent behind the move)
  2  SMA divergence   — 1.0x
  3  Gaps             — 1.0x
  4  Stochastics      — 1.2x  (timing / momentum)
  5  CCI              — 1.2x  (timing / momentum)
  6  Role reversal    — 1.6x  (highest — defines the setup level)

Max weighted score = sum of weights = 9.0
Conviction % = weighted_score / 9.0 * 100  (clipped to ±100)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from signals.base import Bias, SignalResult, TickerAnalysis

#                      Candle  Vol   SMA   Gaps  Stoch  CCI  RoleRev  RS    VWAP  News
WEIGHTS: List[float] = [1.5,   1.5,  1.0,  1.0,  1.2,  1.2,  1.6,   1.3,  1.1,  0.9]
MAX_WEIGHTED = sum(WEIGHTS)   # 12.3 (10 signals)

# Import from __init__ to keep a single source of truth
# (conviction.py uses long-form names for analysis text)
SIG_NAMES_LONG = [
    "Candle pattern",
    "Volume",
    "SMA divergence",
    "Gaps",
    "Stochastics",
    "CCI",
    "Role reversal",
    "Rel. Strength",   # ENH-09
    "VWAP",            # ENH-12
    "News sentiment",  # ENH-18
]
SIG_NAMES = SIG_NAMES_LONG  # alias for backward compat


@dataclass
class ConvictionScore:
    ticker: str
    raw_score: int          # −7 … +7
    weighted_score: float   # −9.0 … +9.0
    conviction_pct: float   # 0 … 100  (absolute, direction separate)
    direction: str          # "bullish" | "bearish" | "neutral"
    grade: str              # A+ / A / B / C / D
    analysis: str           # paragraph commentary
    key_signals: List[str] = field(default_factory=list)
    conflicting: List[str] = field(default_factory=list)

    @property
    def emoji(self) -> str:
        if self.direction == "bullish":
            return "🟢"
        if self.direction == "bearish":
            return "🔴"
        return "⚪"


def _grade(pct: float, direction: str) -> str:
    if direction == "neutral":
        return "D"
    if pct >= 85: return "A+"
    if pct >= 70: return "A"
    if pct >= 55: return "B"
    if pct >= 40: return "C"
    return "D"


def _commentary(ta: TickerAnalysis, ws: float, direction: str,
                key: List[str], conflicts: List[str]) -> str:
    """Generate a 3–4 sentence analysis paragraph."""
    price_str = f"${ta.price:.2f}" if ta.price else "N/A"
    chg_str   = f"{ta.chg_pct:+.2f}%" if ta.chg_pct else "flat"
    mode_str  = "intraday (hourly)" if ta.mode == "Hourly" else "daily"
    score_str = f"{ta.net_score:+d}/7"

    # Opening line — price action summary
    if direction == "bullish":
        opener = (
            f"{ta.ticker} is trading at {price_str} ({chg_str} on the session) and "
            f"shows a net bullish signal score of {score_str} across the {mode_str} chart, "
            f"indicating accumulation and buying pressure."
        )
    elif direction == "bearish":
        opener = (
            f"{ta.ticker} is trading at {price_str} ({chg_str} on the session) and "
            f"shows a net bearish signal score of {score_str} across the {mode_str} chart, "
            f"indicating distribution and selling pressure."
        )
    else:
        opener = (
            f"{ta.ticker} is trading at {price_str} ({chg_str} on the session) with "
            f"a mixed signal score of {score_str} across the {mode_str} chart — "
            f"no dominant directional conviction at this time."
        )

    # Key signals driving conviction
    if key:
        key_line = "The strongest supporting signals are: " + "; ".join(key[:3]) + "."
    else:
        key_line = ""

    # Conflict / caution note
    if conflicts:
        caution = (
            f"Traders should note conflicting signals from {', '.join(conflicts[:2])}, "
            f"which introduce uncertainty and suggest using tighter risk controls."
        )
    else:
        caution = (
            "Signal alignment is strong with no major conflicting indicators, "
            "supporting a higher-conviction setup."
        )

    # Action / watch level
    sma_sig = next((s for s in ta.signals if "SMA" in s.name), None)
    rr_sig  = next((s for s in ta.signals if "reversal" in s.name.lower()), None)
    if rr_sig and rr_sig.detail:
        watch = f"Key level to monitor: {rr_sig.detail.split('·')[0].strip()}."
    elif sma_sig and sma_sig.detail:
        watch = f"20-period SMA context: {sma_sig.detail}."
    else:
        watch = ""

    parts = [opener, key_line, caution, watch]
    return " ".join(p for p in parts if p).strip()


def score_conviction(ta: TickerAnalysis) -> ConvictionScore:
    """Compute weighted conviction score and commentary for one ticker."""
    ws = 0.0
    key_signals: List[str] = []
    conflicts:   List[str] = []

    for i, sig in enumerate(ta.signals):
        w = WEIGHTS[i] if i < len(WEIGHTS) else 1.0
        label_short = SIG_NAMES[i] if i < len(SIG_NAMES) else sig.name

        if sig.bias == Bias.BULL:
            ws += w
            key_signals.append(f"{label_short} ({sig.label})")
        elif sig.bias == Bias.BEAR:
            ws -= w

    # detect conflicts: bull candle but bear momentum, or vice versa
    candle_bias = ta.signals[0].bias if ta.signals else Bias.NEUTRAL
    stoch_bias  = ta.signals[4].bias if len(ta.signals) > 4 else Bias.NEUTRAL
    cci_bias    = ta.signals[5].bias if len(ta.signals) > 5 else Bias.NEUTRAL
    vol_bias    = ta.signals[1].bias if len(ta.signals) > 1 else Bias.NEUTRAL

    if candle_bias != Bias.NEUTRAL and stoch_bias != Bias.NEUTRAL and candle_bias != stoch_bias:
        conflicts.append("stochastics vs candle")
    if candle_bias != Bias.NEUTRAL and cci_bias != Bias.NEUTRAL and candle_bias != cci_bias:
        conflicts.append("CCI vs candle")
    if candle_bias != Bias.NEUTRAL and vol_bias != Bias.NEUTRAL and candle_bias != vol_bias:
        conflicts.append("volume vs candle")

    pct = abs(ws) / MAX_WEIGHTED * 100
    direction = "bullish" if ws > 0 else "bearish" if ws < 0 else "neutral"
    grade = _grade(pct, direction)

    # Only keep bull key signals for bullish, bear-signal labels for bearish
    if direction == "bearish":
        key_signals = []
        for i, sig in enumerate(ta.signals):
            if sig.bias == Bias.BEAR:
                lbl = SIG_NAMES[i] if i < len(SIG_NAMES) else sig.name
                key_signals.append(f"{lbl} ({sig.label})")

    commentary = _commentary(ta, ws, direction, key_signals, conflicts)

    # ENH-16: Multi-timeframe penalty
    from signals.multi_timeframe import mtf_conviction_multiplier
    mtf_mult = mtf_conviction_multiplier(getattr(ta, "mtf_aligned", True))
    if mtf_mult < 1.0:
        conviction_pct = round(conviction_pct * mtf_mult, 1)
        grade_order = ["A+", "A", "B", "C", "D"]
        if grade in grade_order and grade_order.index(grade) < len(grade_order) - 1:
            grade = grade_order[grade_order.index(grade) + 1]

    # ENH-11: Earnings warning
    if getattr(ta, "earnings_soon", False):
        commentary = "⚠ EARNINGS WITHIN 2 DAYS — elevated gap risk. " + commentary

    return ConvictionScore(
        ticker=ta.ticker,
        raw_score=ta.net_score,
        weighted_score=round(ws, 2),
        conviction_pct=round(pct, 1),
        direction=direction,
        grade=grade,
        analysis=commentary,
        key_signals=key_signals[:4],
        conflicting=conflicts,
    )


def top_picks(results: List[TickerAnalysis], n: int = 5) -> Tuple[
        List[Tuple[TickerAnalysis, ConvictionScore]],
        List[Tuple[TickerAnalysis, ConvictionScore]]]:
    """
    Return (top_bull, top_bear) each of up to n entries,
    sorted by conviction_pct descending within their direction.
    """
    scored = [(ta, score_conviction(ta)) for ta in results]
    bulls = sorted(
        [(ta, cs) for ta, cs in scored if cs.direction == "bullish"],
        key=lambda x: x[1].conviction_pct, reverse=True
    )[:n]
    bears = sorted(
        [(ta, cs) for ta, cs in scored if cs.direction == "bearish"],
        key=lambda x: x[1].conviction_pct, reverse=True
    )[:n]
    return bulls, bears
