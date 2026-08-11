"""
signals/boosted.py — live LightGBM / XGBoost / ensemble scoring.

Loads artifacts trained by backtest/boosted_tuner.py:
  models/lgbm_phit_model.json     — LightGBM P(Fib target hit)
  models/lgbm_range_model.json    — favourable excursion quantiles
  models/lgbm_adverse_model.json  — adverse / stop-side excursion quantiles
  models/xgb_phit_model.json      — true XGBoost P(hit)

Runs ALONGSIDE the logistic P(hit) model (signals/phit.py). Does NOT replace
conviction weights or pick ranking. Predictions land on ConvictionScore for the
dashboard ML pages.

Pure Python at inference (no LightGBM / XGBoost binaries on Lambda).

Note: ConvictionScore.xgb_phit historically stores LightGBM P(hit). True XGBoost
lives in xgboost_phit; ens_phit blends logistic + LightGBM + XGBoost.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from signals.lgbm_infer import predict_proba as lgbm_proba
from signals.lgbm_infer import predict_value, trees_from_dump as lgbm_trees
from signals.xgb_infer import predict_proba as xgb_proba
from signals.xgb_infer import trees_from_dump as xgb_trees

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
_ROOT = Path(__file__).parent.parent
PHIT_PATH = _ROOT / "models" / "lgbm_phit_model.json"
RANGE_PATH = _ROOT / "models" / "lgbm_range_model.json"
ADVERSE_PATH = _ROOT / "models" / "lgbm_adverse_model.json"
XGB_PHIT_PATH = _ROOT / "models" / "xgb_phit_model.json"

_DIRECTION_SHORT = {"bullish": "bull", "bearish": "bear"}

_phit_model: Optional[dict] = None
_phit_loaded = False
_range_model: Optional[dict] = None
_range_loaded = False
_adverse_model: Optional[dict] = None
_adverse_loaded = False
_xgb_model: Optional[dict] = None
_xgb_loaded = False
_regime: Optional[Tuple[float, float, float]] = None
_regime_loaded = False


def reset_cache() -> None:
    global _phit_model, _phit_loaded, _range_model, _range_loaded
    global _adverse_model, _adverse_loaded, _xgb_model, _xgb_loaded
    global _regime, _regime_loaded
    _phit_model = None
    _phit_loaded = False
    _range_model = None
    _range_loaded = False
    _adverse_model = None
    _adverse_loaded = False
    _xgb_model = None
    _xgb_loaded = False
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
    if data and data.get("feature_names") and lgbm_trees(data):
        _phit_model = data
        log.info("Loaded LightGBM P(hit) (%d features, AUC %s).",
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
        log.info("Loaded favourable range model (%d features).",
                 len(data["feature_names"]))
    else:
        _range_model = None
    return _range_model


def _load_adverse() -> Optional[dict]:
    global _adverse_model, _adverse_loaded
    if _adverse_loaded:
        return _adverse_model
    _adverse_loaded = True
    data = _load_json(ADVERSE_PATH)
    if data and data.get("feature_names") and data.get("quantiles"):
        _adverse_model = data
        log.info("Loaded adverse/risk range model (%d features).",
                 len(data["feature_names"]))
    else:
        _adverse_model = None
    return _adverse_model


def _load_xgb() -> Optional[dict]:
    global _xgb_model, _xgb_loaded
    if _xgb_loaded:
        return _xgb_model
    _xgb_loaded = True
    data = _load_json(XGB_PHIT_PATH)
    if data and data.get("feature_names") and xgb_trees(data):
        _xgb_model = data
        log.info("Loaded XGBoost P(hit) (%d features, AUC %s).",
                 len(data["feature_names"]), data.get("test_auc"))
    else:
        _xgb_model = None
    return _xgb_model


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


def _predict_quantiles(model: dict, row: List[float]) -> Optional[Tuple[float, float, float]]:
    qs = model["quantiles"]
    try:
        q25 = float(predict_value(lgbm_trees(qs["0.25"]), row))
        q50 = float(predict_value(lgbm_trees(qs["0.50"]), row))
        q75 = float(predict_value(lgbm_trees(qs["0.75"]), row))
    except Exception:
        return None
    q25 = max(0.0, q25)
    q50 = max(0.0, q50)
    q75 = max(0.0, q75)
    ordered = sorted([q25, q50, q75])
    return ordered[0], ordered[1], ordered[2]


def predict_boosted_phit(ta, cs) -> Optional[float]:
    """LightGBM P(Fib target hit). Stored historically as ConvictionScore.xgb_phit."""
    model = _load_phit()
    if model is None:
        return None
    row = _feature_row(ta, cs, model)
    if row is None or len(row) != len(model["feature_names"]):
        return None
    try:
        p = lgbm_proba(lgbm_trees(model), row)
        return round(float(p), 4)
    except Exception:
        log.debug("LightGBM P(hit) failed for %s", getattr(ta, "ticker", "?"),
                  exc_info=True)
        return None


def predict_xgboost_phit(ta, cs) -> Optional[float]:
    """True XGBoost P(Fib target hit)."""
    model = _load_xgb()
    if model is None:
        return None
    row = _feature_row(ta, cs, model)
    if row is None or len(row) != len(model["feature_names"]):
        return None
    try:
        base = float(model.get("base_score", 0.5))
        p = xgb_proba(xgb_trees(model), row, base_score=base)
        return round(float(p), 4)
    except Exception:
        log.debug("XGBoost P(hit) failed for %s", getattr(ta, "ticker", "?"),
                  exc_info=True)
        return None


def predict_ensemble_phit(ta, cs,
                          logistic_phit: Optional[float] = None) -> Optional[float]:
    """
    Simple average of available P(hit) models:
    logistic + LightGBM + XGBoost (whichever are present).
    """
    vals: List[float] = []
    if logistic_phit is None:
        logistic_phit = getattr(cs, "phit", None)
    if logistic_phit is not None:
        vals.append(float(logistic_phit))
    lgbm = getattr(cs, "xgb_phit", None)
    if lgbm is None:
        lgbm = predict_boosted_phit(ta, cs)
    if lgbm is not None:
        vals.append(float(lgbm))
    xgb = getattr(cs, "xgboost_phit", None)
    if xgb is None:
        xgb = predict_xgboost_phit(ta, cs)
    if xgb is not None:
        vals.append(float(xgb))
    if not vals:
        return None
    return round(sum(vals) / len(vals), 4)


def predict_price_range(ta, cs) -> Optional[Dict[str, float]]:
    """
    Predicted favourable price band from quantile excursion model.

    Returns lo/mid/hi absolute prices + *_pct favourable excursion fractions.
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

    qs = _predict_quantiles(model, row)
    if qs is None:
        log.debug("Range prediction failed for %s", getattr(ta, "ticker", "?"),
                  exc_info=True)
        return None
    q25, q50, q75 = qs

    if direction == "bull":
        lo = price * (1.0 + q25)
        mid = price * (1.0 + q50)
        hi = price * (1.0 + q75)
    else:
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


def predict_adverse_range(ta, cs) -> Optional[Dict[str, float]]:
    """
    Predicted adverse (stop-side) price band.

    Bull: prices below entry (adv_lo deepest drawdown … adv_hi shallowest).
    Bear: prices above entry (adv_lo shallowest squeeze … adv_hi deepest).
    """
    model = _load_adverse()
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

    qs = _predict_quantiles(model, row)
    if qs is None:
        return None
    q25, q50, q75 = qs

    if direction == "bull":
        # Adverse = down. Absolute ascending: deepest → shallowest toward entry.
        lo = price * (1.0 - q75)
        mid = price * (1.0 - q50)
        hi = price * (1.0 - q25)
    else:
        # Adverse = up. Absolute ascending: shallowest squeeze → deepest.
        lo = price * (1.0 + q25)
        mid = price * (1.0 + q50)
        hi = price * (1.0 + q75)

    return {
        "lo": round(lo, 2),
        "mid": round(mid, 2),
        "hi": round(hi, 2),
        "lo_pct": round(q25 * 100, 2),
        "mid_pct": round(q50 * 100, 2),
        "hi_pct": round(q75 * 100, 2),
    }


def predict_ev_score(
    ens_phit: Optional[float],
    fav_mid_pct: Optional[float],
    adv_mid_pct: Optional[float],
) -> Optional[float]:
    """
    Rough risk-adjusted expected move (%):
      ens_phit * fav_mid − (1 − ens_phit) * adv_mid
    """
    if ens_phit is None or fav_mid_pct is None or adv_mid_pct is None:
        return None
    p = float(ens_phit)
    return round(p * float(fav_mid_pct) - (1.0 - p) * float(adv_mid_pct), 2)


def phit_model_available() -> bool:
    return _load_phit() is not None


def range_model_available() -> bool:
    return _load_range() is not None


def adverse_model_available() -> bool:
    return _load_adverse() is not None


def xgb_model_available() -> bool:
    return _load_xgb() is not None
