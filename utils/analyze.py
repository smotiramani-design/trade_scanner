"""
utils/analyze.py — shared on-demand single-ticker analysis.

Runs the full engine (10 signals + conviction + Fibonacci + ATR R-plan) for one
ticker and returns a JSON-safe dict. Used by BOTH:
  • web/api.py            — FastAPI backend for local dev
  • analyze_lambda.py     — AWS Lambda Function URL handler for production

Keeping the logic here means there is exactly one implementation, and the
Lambda handler needs no FastAPI/uvicorn dependency in its deployment zip.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional


class InsufficientData(Exception):
    """Raised when a ticker has too little price history to analyse."""


def serialise_fib(f) -> Optional[dict]:
    """Serialise a FibLevels object to a JSON-safe dict (see signals/fibonacci.py)."""
    if not f:
        return None
    return {
        "direction":      getattr(f, "direction", None),
        "anchor_type":    getattr(f, "anchor_type", None),
        "current_price":  getattr(f, "current_price", None),
        "swing_high":     getattr(f, "swing_high", None),
        "swing_low":      getattr(f, "swing_low", None),
        "entry_price":    getattr(f, "entry_price", None),
        "entry_label":    getattr(f, "entry_label", ""),
        "stop_loss":      getattr(f, "stop_loss", None),
        "stop_label":     getattr(f, "stop_label", ""),
        "target_1":       getattr(f, "target_1", None),
        "target_1_label": getattr(f, "target_1_label", ""),
        "target_2":       getattr(f, "target_2", None),
        "target_3":       getattr(f, "target_3", None),
        "risk_reward_t1": getattr(f, "risk_reward_t1", None),
        # Primary take-profit on the correct side of price — the "next ~1 hour"
        # target price when computed on Hourly bars.
        "next_target":    getattr(f, "next_hour_target", None),
        "next_label":     getattr(f, "next_hour_label", ""),
        "support_1":      getattr(f, "support_1", None),
        "resistance_1":   getattr(f, "resistance_1", None),
    }


def serialise_atr(plan) -> Optional[dict]:
    """Serialise an AtrPlan to a JSON-safe dict (see signals/atr.py)."""
    if not plan:
        return None
    return {
        "entry":      getattr(plan, "entry", None),
        "stop":       getattr(plan, "stop", None),
        "target_1":   getattr(plan, "target_1", None),
        "target_2":   getattr(plan, "target_2", None),
        "atr":        getattr(plan, "atr", None),
        "r_distance": getattr(plan, "r_distance", None),
        "multiplier": getattr(plan, "multiplier", None),
        "direction":  getattr(plan, "direction", None),
    }


def serialise_conviction(cs) -> dict:
    """Serialise a ConvictionScore to a JSON-safe dict."""
    return {
        "ticker":         cs.ticker,
        "raw_score":      cs.raw_score,
        "weighted_score": cs.weighted_score,
        "conviction_pct": cs.conviction_pct,
        "direction":      cs.direction,
        "grade":          cs.grade,
        "analysis":       cs.analysis,
        "key_signals":    cs.key_signals,
        "conflicting":    cs.conflicting,
    }


def analyze_ticker(ticker: str, hourly: bool = True) -> dict:
    """
    Run the full engine for a single ticker and return a JSON-safe dict.

    With hourly=True the Fibonacci plan is computed on Hourly bars, so
    fib["next_target"] is the projected target price for roughly the next hour.
    SPY bars are fetched so the (top-weighted) Relative-Strength signal is
    accurate, matching the intraday scanner.

    Raises InsufficientData when the ticker lacks enough price history.
    """
    from data.yahoo_client import get_bars
    from signals import run_all, SIG_NAMES
    from signals.conviction import direction_from_signals, score_conviction
    from signals.base import TickerAnalysis
    from signals.fibonacci import compute_fibonacci
    from signals.atr import compute_atr_plan

    sym = ticker.upper().strip()
    bars = get_bars(sym, market_open=hourly)
    if len(bars) < 30:
        raise InsufficientData(f"Insufficient price history for {sym}")

    # SPY benchmark for the Relative-Strength signal (best-effort).
    try:
        spy_bars = get_bars("SPY", market_open=hourly)
    except Exception:
        spy_bars = None

    mode = "Hourly" if hourly else "Daily"
    sigs = run_all(bars, spy_bars=spy_bars, mode=mode, ticker=sym)

    prev = bars[-2].close if len(bars) >= 2 and bars[-2].close else bars[-1].close
    chg = round((bars[-1].close / prev - 1.0) * 100, 2) if prev else 0.0

    ta = TickerAnalysis(
        ticker=sym, price=bars[-1].close, chg_pct=chg,
        volume=bars[-1].volume, bars=len(bars), mode=mode, signals=sigs,
    )
    trade_dir = direction_from_signals(sigs)
    ta.fib = compute_fibonacci(
        sym, bars, bars[-1].close, ta.net_score, direction=trade_dir,
    )
    ta.atr_plan = compute_atr_plan(
        bars, bars[-1].close, ta.net_score, direction=trade_dir,
    )
    ta.atr_stop = ta.atr_plan.stop if ta.atr_plan else None
    cs = score_conviction(ta)

    return {
        "ticker":     sym,
        "price":      round(bars[-1].close, 2),
        "chg_pct":    chg,
        "mode":       mode,
        "net_score":  ta.net_score,
        "verdict":    getattr(ta, "verdict", ""),
        "conviction": serialise_conviction(cs),
        "signals":    [{"name": n, "bias": s.bias.value, "label": s.label, "detail": s.detail}
                       for n, s in zip(SIG_NAMES, sigs)],
        "fib":        serialise_fib(ta.fib),
        "atr":        serialise_atr(ta.atr_plan),
        "as_of":      datetime.now().isoformat(),
    }
