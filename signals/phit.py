"""
signals/phit.py — live P(hit) scoring for the scanner.

Loads the model trained by backtest/logistic_tuner.py (models/phit_model.json) and
predicts, for a scored ticker, the probability that its Fibonacci target will be
hit. This is the "rank by P(hit)" step: instead of ranking only by the conviction
% (which uses just the 10 signal weights), the scanner can rank surfaced picks by
the FULL model — signals + pick-context + market-regime — exactly as it was
trained and evaluated (walk-forward AUC ≈ 0.81).

Design notes:
  * Pure Python. No sklearn or numpy needed at inference — prediction is just a
    dot product through a sigmoid. This keeps the scanner (and its Lambda bundle)
    light and means a missing ML stack never breaks a scan.
  * Feature construction is delegated to logistic_tuner.row_for_pick, the SAME
    code path used in training, so features can never silently drift.
  * Graceful degradation: if the model artifact is absent or malformed, every
    call returns None and callers fall back to conviction-based ranking.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

_DIRECTION_SHORT = {"bullish": "bull", "bearish": "bear"}

# Process-lifetime caches. _model_loaded / _regime_loaded distinguish "not tried
# yet" from "tried and unavailable" so we never refetch SPY on every ticker.
_model: Optional[dict] = None
_model_loaded = False
_regime: Optional[Tuple[float, float, float]] = None
_regime_loaded = False
_warned_regime = False


def _load_model() -> Optional[dict]:
    """Read and validate the P(hit) artifact once per process."""
    global _model, _model_loaded
    if _model_loaded:
        return _model
    _model_loaded = True

    try:
        from backtest.logistic_tuner import MODEL_PATH
    except Exception:  # backtest package not bundled — degrade to conviction ranking
        log.debug("backtest.logistic_tuner unavailable — using conviction ranking.")
        return None
    if not MODEL_PATH.exists():
        log.debug("No P(hit) model at %s — using conviction ranking.", MODEL_PATH)
        return None
    try:
        data = json.loads(MODEL_PATH.read_text())
        coefs = data["coefs"]
        if len(coefs) != len(data["feature_names"]):
            log.warning("P(hit) model malformed (coef/name mismatch) — ignoring.")
            return None
        _model = data
        log.info("Loaded P(hit) model (%d features, trained on %s rows, AUC %s).",
                 len(coefs), data.get("n_samples"), data.get("test_auc"))
    except (ValueError, KeyError, OSError):
        log.exception("Could not load P(hit) model — using conviction ranking.")
        _model = None
    return _model


def _current_regime() -> Optional[Tuple[float, float, float]]:
    """SPY market regime as of the last completed session (no lookahead), cached."""
    global _regime, _regime_loaded
    if _regime_loaded:
        return _regime
    _regime_loaded = True
    try:
        from backtest.logistic_tuner import load_spy_regime
        lookup = load_spy_regime()
        if lookup is not None:
            _regime = lookup.for_date(datetime.now(ET).date())
    except Exception as e:  # network/driver issues must never break a scan
        log.debug("Regime unavailable for P(hit) (%s).", e)
        _regime = None
    return _regime


def reset_cache() -> None:
    """Drop cached model + regime (useful in tests or after retraining mid-process)."""
    global _model, _model_loaded, _regime, _regime_loaded, _warned_regime
    _model = None
    _model_loaded = False
    _regime = None
    _regime_loaded = False
    _warned_regime = False


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _predict_row(model: dict, row: List[float]) -> Optional[float]:
    coefs = model["coefs"]
    if len(row) != len(coefs):
        log.warning("P(hit) feature-length mismatch (row=%d, model=%d) — skipping.",
                    len(row), len(coefs))
        return None
    n_sig = int(model["n_signal_cols"])
    mean = model.get("context_mean")
    std = model.get("context_std")
    z = float(model["intercept"])
    for i, (c, x) in enumerate(zip(coefs, row)):
        if i >= n_sig and mean is not None and std is not None:
            j = i - n_sig
            s = std[j] if std[j] else 1.0
            x = (x - mean[j]) / s
        z += c * x
    return _sigmoid(z)


def predict_phit(ta, cs) -> Optional[float]:
    """
    Predicted probability (0..1) that this ticker hits its Fib target.

    ta: signals.base.TickerAnalysis   cs: signals.conviction.ConvictionScore
    Returns None when no model is available or the pick is directionless.
    """
    global _warned_regime
    model = _load_model()
    if model is None:
        return None

    direction = _DIRECTION_SHORT.get(getattr(cs, "direction", ""), None)
    if direction is None:  # neutral picks weren't part of training
        return None

    # Build the aligned 10-signal vector the same way training does.
    from signals.base import Bias
    from backtest.logistic_tuner import LabeledPick, row_for_pick, _aligned

    signals_feat = [_aligned(s.bias.value, direction) for s in ta.signals]

    regime_tuple = None
    if model.get("include_regime"):
        regime_tuple = _current_regime()
        if regime_tuple is None:
            regime_tuple = (0.0, 0.0, 0.0)  # matches training's missing-regime encoding
            if not _warned_regime:
                log.warning("SPY regime unavailable — P(hit) uses neutral regime.")
                _warned_regime = True

    pick = LabeledPick(
        direction     = direction,
        signals_feat  = signals_feat,
        hit           = 0,  # unused at inference
        trade_date    = datetime.now(ET).date(),
        et_time       = datetime.now(ET).strftime("%H:%M"),
        conviction    = float(getattr(cs, "conviction_pct", 0.0)),
        mtf_aligned   = 1 if getattr(ta, "mtf_aligned", True) else 0,
        earnings_soon = 1 if getattr(ta, "earnings_soon", False) else 0,
        chg_pct       = float(getattr(ta, "chg_pct", 0.0) or 0.0),
        atr_stop      = getattr(ta, "atr_stop", None),
        price         = getattr(ta, "price", None),
    )
    row = row_for_pick(
        pick, regime_tuple,
        include_context=bool(model.get("include_context", True)),
        include_regime=bool(model.get("include_regime", True)),
    )
    try:
        p = _predict_row(model, row)
    except Exception:
        log.debug("P(hit) prediction failed for %s", getattr(ta, "ticker", "?"),
                  exc_info=True)
        return None
    return round(p, 4) if p is not None else None


def model_available() -> bool:
    """True if a usable P(hit) model is loaded/loadable."""
    return _load_model() is not None
