"""
signals/xgb_infer.py — Pure-Python XGBoost JSON-dump walker.

Training dumps trees via booster.get_dump(dump_format='json'); Lambda walks
them with no native XGBoost dependency (same idea as signals/lgbm_infer.py).
"""
from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Sequence, Union


def _feat_index(split: str) -> int:
    """XGBoost dump uses 'f0', 'f1', … when trained on a numpy matrix."""
    if split.startswith("f") and split[1:].isdigit():
        return int(split[1:])
    # Named features — caller must map; fallback hash-less fail → 0
    try:
        return int(split)
    except ValueError:
        return 0


def _eval_node(node: Dict[str, Any], row: Sequence[float]) -> float:
    if "leaf" in node:
        return float(node["leaf"])
    feat_i = _feat_index(str(node.get("split", "f0")))
    thr = float(node.get("split_condition", 0.0))
    x = float(row[feat_i]) if feat_i < len(row) else float("nan")
    missing = int(node.get("missing", node.get("yes", 0)))
    yes_id = int(node.get("yes", 0))
    no_id = int(node.get("no", 0))

    if x != x:  # NaN
        target = missing
    elif x < thr:  # XGBoost default: yes branch is "<"
        target = yes_id
    else:
        target = no_id

    children = node.get("children") or []
    child_map = {int(c["nodeid"]): c for c in children if "nodeid" in c}
    child = child_map.get(target)
    if child is None:
        return 0.0
    return _eval_node(child, row)


def trees_from_dump(dump: Union[Dict[str, Any], List[Any]]) -> List[Dict[str, Any]]:
    """Accept our artifact ({trees: [...]}) or a raw list of tree JSON strings/dicts."""
    if isinstance(dump, dict):
        raw = dump.get("trees") or dump.get("tree_info") or []
    else:
        raw = dump
    trees: List[Dict[str, Any]] = []
    for t in raw:
        if isinstance(t, str):
            trees.append(json.loads(t))
        elif isinstance(t, dict):
            trees.append(t)
    return trees


def predict_raw(trees: Sequence[Dict[str, Any]], row: Sequence[float]) -> float:
    return sum(_eval_node(t, row) for t in trees)


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def predict_proba(trees: Sequence[Dict[str, Any]], row: Sequence[float],
                  base_score: float = 0.5) -> float:
    """
    Binary logistic XGBoost: raw sum is the margin; base_score is the prior
    probability (XGBoost default 0.5 → logit 0).
    """
    # Convert base_score probability to logit and add to margin.
    eps = 1e-7
    p0 = min(max(base_score, eps), 1.0 - eps)
    base_margin = math.log(p0 / (1.0 - p0))
    return sigmoid(base_margin + predict_raw(trees, row))
