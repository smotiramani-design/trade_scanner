"""
signals/boosted.py — live LightGBM P(hit) + price-range scoring.

Loads artifacts trained by backtest/boosted_tuner.py:
  models/lgbm_phit_model.json   — gradient-boosted P(Fib target hit)
  models/lgbm_range_model.json  — quantile regression of favourable excursion

Runs ALONGSIDE the logistic P(hit) model (signals/phit.py). Does NOT replace
conviction weights or pick ranking — those stay on the logistic path. Predictions
are stored on ConvictionScore for the dashboard's Boosted Models pages.

Pure Python at inference (no LightGBM binary needed on Lambda).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from signals.lgbm_infer import predict_proba, predict_value, trees_from_dump

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
_ROOT = Path(__file__).parent.parent
PHIT_PATH = _ROOT / "models" / "lgbm_phit_model.json"
RANGE_PATH = _ROOT / "models" / "lgbm_range_model.json"

_DIRECTION_SHORT = {"bullish": "bull", "bearish": "bear"}

_phit_model: Optional[dict] = None
_phit_loaded = False
_range_model: Optional[dict] = None
_range_loaded = False
_regime: Optional[Tuple[float, float, float]] = None
_regime_loaded = False


def reset_cache() -> None:
    global _phit_model, _phit_loaded, _range_model, _range_loaded
    global _regime, _regime_loaded
    _phit_model = None
    _phit_loaded = False
    _range_model = None
    _range_loaded = False
    _regime = None
    _regime_loaded = False


def _load_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (ValueError, OSError):
        log.exception("Could not load boosted model at %s", path)
        return None


def _load_phit() -> Optional[dict]:
    global _phit_model, _phit_loaded
    if _phit_loaded:
        return _phit_model
    _phit_loaded = True
    data = _load_json(PHIT_PATH)
    if data and data.get("feature_names") and trees_from_dump(data):
        _phit_model = data
        log.info("Loaded boosted P(hit) model (%d features, AUC %s).",
                 len(data["feature_names"]), data.get("test_auc"))
    else:
        _phit_model = None
    return _phit_model


def _load_range() -> Optional[dict]:
    global _range_model, _range_loaded
    if _range_loaded:
        return _range_model
    _range_loaded = True
    data = _load_json(RANGE_PATH)
    if data and data.get("feature_names") and data.get("quantiles"):
        _range_model = data
        log.info("Loaded price-range model (%d features).",
                 len(data["feature_names"]))
    else:
        _range_model = None
    return _range_model


def _current_regime() -> Optional[Tuple[float, float, float]]:
    global _regime, _regime_loaded
    if _regime_loaded:
        return _regime
    _regime_loaded = True
    try:
        from backtest.logistic_tuner import load_spy_regime
        lookup = load_spy_regime()
        if lookup is not None:
            _regime = lookup.for_date(datetime.now(ET).date())
    except Exception as e:
        log.debug("Regime unavailable for boosted models (%s).", e)
        _regime = None
    return _regime


def _feature_row(ta, cs, model: dict) -> Optional[List[float]]:
    direction = _DIRECTION_SHORT.get(getattr(cs, "direction", ""), None)
    if direction is None:
        return None
    from backtest.logistic_tuner import LabeledPick, row_for_pick, _aligned

    signals_feat = [_aligned(s.bias.value, direction) for s in ta.signals]
    regime_tuple = None
    if model.get("include_regime"):
        regime_tuple = _current_regime() or (0.0, 0.0, 0.0)

    pick = LabeledPick(
        direction     = direction,
        signals_feat  = signals_feat,
        hit           = 0,
        trade_date    = datetime.now(ET).date(),
        et_time       = datetime.now(ET).strftime("%H:%M"),
        conviction    = float(getattr(cs, "conviction_pct", 0.0)),
        mtf_aligned   = 1 if getattr(ta, "mtf_aligned", True) else 0,
        earnings_soon = 1 if getattr(ta, "earnings_soon", False) else 0,
        chg_pct       = float(getattr(ta, "chg_pct", 0.0) or 0.0),
        atr_stop      = getattr(ta, "atr_stop", None),
        price         = getattr(ta, "price", None),
    )
    return row_for_pick(
        pick, regime_tuple,
        include_context=bool(model.get("include_context", True)),
        include_regime=bool(model.get("include_regime", True)),
    )


def predict_boosted_phit(ta, cs) -> Optional[float]:
    """Gradient-boosted P(Fib target hit). None if model absent / neutral."""
    model = _load_phit()
    if model is None:
        return None
    row = _feature_row(ta, cs, model)
    if row is None or len(row) != len(model["feature_names"]):
        return None
    try:
        p = predict_proba(trees_from_dump(model), row)
        return round(float(p), 4)
    except Exception:
        log.debug("Boosted P(hit) failed for %s", getattr(ta, "ticker", "?"),
                  exc_info=True)
        return None


def predict_price_range(ta, cs) -> Optional[Dict[str, float]]:
    """
    Predicted favourable price band from quantile excursion model.

    Returns dict with keys:
      lo, mid, hi          — absolute prices (lo ≤ mid ≤ hi)
      lo_pct, mid_pct, hi_pct — favourable excursion fractions
    or None if unavailable.
    """
    model = _load_range()
    if model is None:
        return None
    price = getattr(ta, "price", None)
    if not price or price <= 0:
        return None
    direction = _DIRECTION_SHORT.get(getattr(cs, "direction", ""), None)
    if direction is None:
        return None

    row = _feature_row(ta, cs, model)
    if row is None or len(row) != len(model["feature_names"]):
        return None

    qs = model["quantiles"]
    try:
        q25 = float(predict_value(trees_from_dump(qs["0.25"]), row))
        q50 = float(predict_value(trees_from_dump(qs["0.50"]), row))
        q75 = float(predict_value(trees_from_dump(qs["0.75"]), row))
    except Exception:
        log.debug("Range prediction failed for %s", getattr(ta, "ticker", "?"),
                  exc_info=True)
        return None

    # Clamp to non-negative excursions (can't move "favourably" by a negative %).
    q25 = max(0.0, q25)
    q50 = max(0.0, q50)
    q75 = max(0.0, q75)
    # Enforce order q25 ≤ q50 ≤ q75 for a sane band.
    ordered = sorted([q25, q50, q75])
    q25, q50, q75 = ordered[0], ordered[1], ordered[2]

    if direction == "bull":
        lo = price * (1.0 + q25)
        mid = price * (1.0 + q50)
        hi = price * (1.0 + q75)
    else:
        # Bear: favourable = down. Absolute prices ascending: deepest → shallowest.
        hi = price * (1.0 - q25)
        mid = price * (1.0 - q50)
        lo = price * (1.0 - q75)
        if lo > hi:
            lo, hi = hi, lo

    return {
        "lo": round(lo, 2),
        "mid": round(mid, 2),
        "hi": round(hi, 2),
        "lo_pct": round(q25 * 100, 2),
        "mid_pct": round(q50 * 100, 2),
        "hi_pct": round(q75 * 100, 2),
    }


def phit_model_available() -> bool:
    return _load_phit() is not None


def range_model_available() -> bool:
    return _load_range() is not None
