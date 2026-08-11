"""
signals/lgbm_infer.py — Pure-Python LightGBM dump-model walker.

Why this exists: Lambda cannot ship LightGBM/XGBoost (compiled deps + size).
Training (`backtest/boosted_tuner.py`) dumps the fitted booster via
`booster.dump_model()` to JSON; this module walks those trees at scan time
with zero native dependencies — same pattern as signals/phit.py for logistic.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence


def _eval_node(node: Dict[str, Any], row: Sequence[float]) -> float:
    """Recursively evaluate one LightGBM tree node against a feature row."""
    if "leaf_value" in node:
        return float(node["leaf_value"])

    feat_i = int(node["split_feature"])
    thr = float(node["threshold"])
    x = float(row[feat_i]) if feat_i < len(row) else float("nan")

    # LightGBM default: missing goes left when default_left is true.
    default_left = bool(node.get("default_left", True))
    decision = node.get("decision_type", "<=")

    if x != x:  # NaN
        go_left = default_left
    elif decision in ("<=", "<"):
        go_left = x <= thr if decision == "<=" else x < thr
    elif decision in (">=", ">"):
        go_left = x >= thr if decision == ">=" else x > thr
    else:
        go_left = x <= thr

    child = node["left_child"] if go_left else node["right_child"]
    return _eval_node(child, row)


def predict_raw(trees: Sequence[Dict[str, Any]], row: Sequence[float]) -> float:
    """Sum leaf values across trees (= raw margin / logit for binary)."""
    total = 0.0
    for t in trees:
        structure = t.get("tree_structure") if isinstance(t, dict) else None
        if structure is None and isinstance(t, dict) and "leaf_value" in t:
            structure = t
        if structure is None:
            continue
        total += _eval_node(structure, row)
    return total


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def predict_proba(trees: Sequence[Dict[str, Any]], row: Sequence[float]) -> float:
    """Binary classifier probability from a LightGBM dump."""
    return sigmoid(predict_raw(trees, row))


def predict_value(trees: Sequence[Dict[str, Any]], row: Sequence[float]) -> float:
    """Regression / quantile prediction from a LightGBM dump."""
    return predict_raw(trees, row)


def trees_from_dump(dump: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract tree list from a LightGBM dump_model() dict or our artifact."""
    if "tree_info" in dump:
        return list(dump["tree_info"])
    if "trees" in dump:
        return list(dump["trees"])
    return []
