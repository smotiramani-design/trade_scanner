"""
signals/conviction.py — conviction scoring and analysis commentary.

Conviction goes beyond the raw net score by weighting signals
that tend to have higher predictive value and penalizing
conflicting or low-quality setups.

The weights below are LEARNED, not hand-tuned. They are produced by
backtest/logistic_tuner.py, which fits an L2-regularised logistic regression on
the labeled scanned universe (scan_features, tagged end-of-day with whether each
Fibonacci target was hit) and maps the learned signal coefficients onto the
0.5–2.0 conviction range. Re-run `python -m backtest.logistic_tuner --apply`
weekly as more labeled rows accumulate; the values here update automatically.

Weights per signal (index matches SIGNAL_MODULES order — last learned fit,
630 labeled rows, walk-forward AUC 0.812):
  0  Candle pattern   — 0.88x
  1  Volume           — 1.64x  (confirms intent behind the move)
  2  SMA divergence   — 1.67x  (strongly predictive)
  3  Gaps             — 1.04x
  4  Stochastics      — 0.93x  (timing / momentum)
  5  CCI              — 0.50x  (floored — noisiest signal)
  6  Role reversal    — 1.32x  (defines the setup level)
  7  Rel. Strength    — 2.00x  (maxed — most predictive signal)
  8  VWAP             — 1.06x
  9  News sentiment   — 0.89x

Max weighted score = sum of weights ≈ 11.9
Conviction % = weighted_score / MAX_WEIGHTED * 100  (clipped to ±100)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from signals.base import Bias, SignalResult, TickerAnalysis

#                      Candle  Vol   SMA   Gaps  Stoch  CCI  RoleRev  RS    VWAP  News
# Learned by backtest/logistic_tuner.py (see module docstring). Do not hand-edit;
# re-run `python -m backtest.logistic_tuner --apply` to refresh.
WEIGHTS: List[float] = [0.77, 1.86, 1.88, 0.88, 0.99, 0.5, 0.96, 2.0, 0.95, 1.02]
MAX_WEIGHTED = sum(WEIGHTS)   # ≈ 11.9 (10 signals)

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
    weighted_score: float   # −11.9 … +11.9  (±MAX_WEIGHTED)
    conviction_pct: float   # 0 … 100  (absolute, direction separate)
    direction: str          # "bullish" | "bearish" | "neutral"
    grade: str              # A+ / A / B / C / D
    analysis: str           # paragraph commentary
    key_signals: List[str] = field(default_factory=list)
    conflicting: List[str] = field(default_factory=list)
    phit: Optional[float] = None   # model P(fib target hit), 0..1; None if no model

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


def weighted_score_and_direction(
    signals: List[SignalResult],
) -> Tuple[float, str]:
    """
    Same weighted direction used for picks, Fib targets, and commentary.

    Raw net_score (bull-count − bear-count) can disagree with this when a few
    high-weight signals outweigh more low-weight ones. Always prefer this for
    trade direction so bull picks get upside targets and bear picks downside.
    """
    ws = 0.0
    for i, sig in enumerate(signals):
        w = WEIGHTS[i] if i < len(WEIGHTS) else 1.0
        if sig.bias == Bias.BULL:
            ws += w
        elif sig.bias == Bias.BEAR:
            ws -= w
    direction = "bullish" if ws > 0 else "bearish" if ws < 0 else "neutral"
    return ws, direction


def direction_from_signals(signals: List[SignalResult]) -> str:
    """Weighted conviction direction: 'bullish' | 'bearish' | 'neutral'."""
    return weighted_score_and_direction(signals)[1]


def _commentary(ta: TickerAnalysis, ws: float, direction: str,
                key: List[str], conflicts: List[str]) -> str:
    """Generate a 3–4 sentence analysis paragraph."""
    price_str = f"${ta.price:.2f}" if ta.price else "N/A"
    chg_str   = f"{ta.chg_pct:+.2f}%" if ta.chg_pct else "flat"
    mode_str  = "intraday (hourly)" if ta.mode == "Hourly" else "daily"
    score_str = f"{ta.net_score:+d}/{len(ta.signals)}"
    # Raw net score can disagree with weighted direction — don't call a
    # negative score "bullish" (or vice versa). State both clearly.
    raw_note = f"raw net score {score_str}"

    # Opening line — price action summary
    if direction == "bullish":
        opener = (
            f"{ta.ticker} is trading at {price_str} ({chg_str} on the session) and "
            f"shows weighted bullish conviction ({raw_note}) across the {mode_str} chart, "
            f"indicating accumulation and buying pressure."
        )
    elif direction == "bearish":
        opener = (
            f"{ta.ticker} is trading at {price_str} ({chg_str} on the session) and "
            f"shows weighted bearish conviction ({raw_note}) across the {mode_str} chart, "
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
    ws, direction = weighted_score_and_direction(ta.signals)
    key_signals: List[str] = []
    conflicts:   List[str] = []

    for i, sig in enumerate(ta.signals):
        label_short = SIG_NAMES[i] if i < len(SIG_NAMES) else sig.name
        if sig.bias == Bias.BULL:
            key_signals.append(f"{label_short} ({sig.label})")

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
        pct   = round(pct * mtf_mult, 1)
        grade = _grade(pct, direction)   # recompute grade at reduced conviction

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


def _attach_phit(scored: List[Tuple[TickerAnalysis, ConvictionScore]]) -> bool:
    """
    Enrich each ConvictionScore with the model's P(hit), in place.

    Returns True if a model produced at least one probability (so callers can
    rank by P(hit)); False means fall back to conviction ranking. Imported
    lazily so the scanner works fine with no ML artifact present.
    """
    try:
        from signals.phit import predict_phit, model_available
    except Exception:
        return False
    if not model_available():
        return False
    any_scored = False
    for ta, cs in scored:
        cs.phit = predict_phit(ta, cs)
        any_scored = any_scored or cs.phit is not None
    return any_scored


def top_picks(results: List[TickerAnalysis], n: int = 5) -> Tuple[
        List[Tuple[TickerAnalysis, ConvictionScore]],
        List[Tuple[TickerAnalysis, ConvictionScore]]]:
    """
    Return (top_bull, top_bear) each of up to n entries.

    When a trained P(hit) model is available (models/phit_model.json), picks are
    ranked by the model's predicted probability of hitting the Fib target —
    which uses the full signal + context + regime model. Otherwise they fall
    back to ranking by conviction_pct. Conviction % is always tie-breaker so
    ordering stays deterministic.
    """
    scored = [(ta, score_conviction(ta)) for ta in results]
    use_phit = _attach_phit(scored)

    def _key(item: Tuple[TickerAnalysis, ConvictionScore]):
        cs = item[1]
        primary = cs.phit if (use_phit and cs.phit is not None) else -1.0
        return (primary, cs.conviction_pct)

    bulls = sorted(
        [(ta, cs) for ta, cs in scored if cs.direction == "bullish"],
        key=_key, reverse=True
    )[:n]
    bears = sorted(
        [(ta, cs) for ta, cs in scored if cs.direction == "bearish"],
        key=_key, reverse=True
    )[:n]
    return bulls, bears
