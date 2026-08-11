"""
backtest/boosted_tuner.py — Gradient-boosted P(hit) + predicted price range.

Trains TWO LightGBM models on the same labeled scan_features / picks data the
logistic tuner uses, and saves them as JSON tree dumps for pure-Python inference
(signals/boosted.py) — no LightGBM binary needed on Lambda.

  1) P(hit) classifier  → models/lgbm_phit_model.json
     Same label as logistic: did the Fib target get hit?
  2) Price-range quantile regressors → models/lgbm_range_model.json
     Label = favourable excursion in the Fib window
       bull: (window_high − price) / price
       bear: (price − window_low) / price
     Predicts 25th / 50th / 75th percentiles → absolute price band at scan time.

These models run ALONGSIDE the existing logistic Fib pipeline. They do NOT
overwrite conviction WEIGHTS or replace logistic ranking.

Usage:
  python -m backtest.boosted_tuner                  # train + report
  python -m backtest.boosted_tuner --save-db        # also log to ml_boosted_runs
  python -m backtest.boosted_tuner --days 60
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from backtest.logistic_tuner import (
    LabeledPick,
    N_SIGNALS,
    build_design_matrix,
    load_spy_regime,
    load_training_data,
    selection_bias,
)

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

MODELS_DIR = Path(__file__).parent.parent / "models"
PHIT_PATH = MODELS_DIR / "lgbm_phit_model.json"
RANGE_PATH = MODELS_DIR / "lgbm_range_model.json"

QUANTILES = (("0.25", 0.25), ("0.50", 0.50), ("0.75", 0.75))


def _require_lgbm():
    try:
        import lightgbm as lgb  # noqa: F401
        return lgb
    except ImportError as e:
        raise SystemExit(
            "lightgbm is required for boosted_tuner.\n"
            "Install with:  pip install lightgbm\n"
            f"({e})"
        )


def _walk_forward_split(n: int, test_frac: float = 0.3) -> int:
    return max(1, int(round(n * (1.0 - test_frac))))


def _feature_importance(booster, names: List[str]) -> List[Dict]:
    gain = booster.feature_importance(importance_type="gain")
    pairs = sorted(
        [{"name": names[i], "gain": float(gain[i])} for i in range(len(names))],
        key=lambda x: -x["gain"],
    )
    return pairs


def train_phit(
    X, y, names: List[str], *, test_frac: float = 0.3
) -> Tuple[dict, dict]:
    """Fit LightGBM binary classifier. Returns (artifact_dict, metrics)."""
    import numpy as np
    from lightgbm import LGBMClassifier
    from sklearn.metrics import accuracy_score, roc_auc_score

    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=int)
    n = len(y)
    split = _walk_forward_split(n, test_frac)
    Xtr, Xte = X[:split], X[split:]
    ytr, yte = y[:split], y[split:]

    clf = LGBMClassifier(
        n_estimators=100,
        learning_rate=0.08,
        max_depth=4,
        num_leaves=15,
        min_child_samples=40,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_lambda=1.0,
        class_weight="balanced",
        random_state=42,
        verbosity=-1,
    )
    clf.fit(Xtr, ytr)
    proba_te = clf.predict_proba(Xte)[:, 1]
    pred_te = (proba_te >= 0.5).astype(int)
    test_acc = float(accuracy_score(yte, pred_te)) if len(yte) else None
    test_auc = None
    if len(yte) and len(set(yte.tolist())) == 2:
        test_auc = float(roc_auc_score(yte, proba_te))

    # Refit on ALL data for the shipped model.
    clf_full = LGBMClassifier(
        n_estimators=100,
        learning_rate=0.08,
        max_depth=4,
        num_leaves=15,
        min_child_samples=40,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_lambda=1.0,
        class_weight="balanced",
        random_state=42,
        verbosity=-1,
    )
    clf_full.fit(X, y)
    dump = clf_full.booster_.dump_model()
    importance = _feature_importance(clf_full.booster_, names)

    metrics = {
        "n_samples": int(n),
        "n_hits": int(y.sum()),
        "n_misses": int(n - y.sum()),
        "base_rate": round(100.0 * float(y.mean()), 1) if n else None,
        "n_train": int(len(ytr)),
        "n_test": int(len(yte)),
        "test_acc": round(test_acc * 100, 1) if test_acc is not None else None,
        "test_auc": round(test_auc, 4) if test_auc is not None else None,
        "feature_importance": importance,
    }
    artifact = {
        "version": 1,
        "kind": "phit_classifier",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "feature_names": list(names),
        "n_signal_cols": N_SIGNALS,
        "include_context": True,
        "include_regime": True,
        "objective": "binary",
        "tree_info": dump.get("tree_info", []),
        "test_auc": metrics["test_auc"],
        "n_samples": metrics["n_samples"],
        "feature_importance": importance,
    }
    return artifact, metrics


def train_range(
    X, y_exc, names: List[str], *, test_frac: float = 0.3
) -> Tuple[dict, dict]:
    """Fit three LightGBM quantile regressors on favourable excursion."""
    import numpy as np
    from lightgbm import LGBMRegressor
    from sklearn.metrics import mean_absolute_error

    X = np.asarray(X, dtype=float)
    y = np.asarray(y_exc, dtype=float)
    n = len(y)
    split = _walk_forward_split(n, test_frac)
    Xtr, Xte = X[:split], X[split:]
    ytr, yte = y[:split], y[split:]

    quantiles_art: Dict[str, dict] = {}
    coverage = {}
    maes = {}
    importance_mid = []

    for qkey, alpha in QUANTILES:
        reg = LGBMRegressor(
            objective="quantile",
            alpha=alpha,
            n_estimators=80,
            learning_rate=0.08,
            max_depth=3,
            num_leaves=12,
            min_child_samples=40,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            random_state=42,
            verbosity=-1,
        )
        reg.fit(Xtr, ytr)
        pred_te = reg.predict(Xte)
        # Empirical coverage: fraction of yte ≤ predicted quantile
        if len(yte):
            coverage[qkey] = round(float(np.mean(yte <= pred_te)), 3)
            maes[qkey] = round(float(mean_absolute_error(yte, pred_te)), 4)

        reg_full = LGBMRegressor(
            objective="quantile",
            alpha=alpha,
            n_estimators=80,
            learning_rate=0.08,
            max_depth=3,
            num_leaves=12,
            min_child_samples=40,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            random_state=42,
            verbosity=-1,
        )
        reg_full.fit(X, y)
        dump = reg_full.booster_.dump_model()
        quantiles_art[qkey] = {"trees": dump.get("tree_info", []), "alpha": alpha}
        if abs(alpha - 0.50) < 1e-9:
            importance_mid = _feature_importance(reg_full.booster_, names)

    metrics = {
        "n_samples": int(n),
        "n_train": int(len(ytr)),
        "n_test": int(len(yte)),
        "mean_excursion_pct": round(100.0 * float(y.mean()), 2) if n else None,
        "median_excursion_pct": round(100.0 * float(np.median(y)), 2) if n else None,
        "test_mae": maes,
        "test_coverage": coverage,
        "feature_importance": importance_mid,
    }
    artifact = {
        "version": 1,
        "kind": "range_quantile",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "feature_names": list(names),
        "n_signal_cols": N_SIGNALS,
        "include_context": True,
        "include_regime": True,
        "quantiles": {
            "0.25": {"tree_info": quantiles_art["0.25"]["trees"]},
            "0.50": {"tree_info": quantiles_art["0.50"]["trees"]},
            "0.75": {"tree_info": quantiles_art["0.75"]["trees"]},
        },
        "n_samples": metrics["n_samples"],
        "test_mae": metrics["test_mae"],
        "test_coverage": metrics["test_coverage"],
        "feature_importance": importance_mid,
    }
    return artifact, metrics


def save_artifact(path: Path, artifact: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2))
    log.info("Saved %s", path)


def save_run(
    *,
    source: str,
    days: Optional[int],
    phit_metrics: dict,
    range_metrics: Optional[dict],
    bias: Optional[dict],
) -> Optional[int]:
    """Persist one ml_boosted_runs row for the dashboard."""
    if not config.DB_ENABLED:
        log.warning("DB disabled — not saving boosted run.")
        return None

    now_et = datetime.now(timezone.utc).astimezone(ET)
    from utils.db_writer import init_db
    from backtest.logistic_tuner import _connect

    conn = _connect()
    try:
        init_db(conn)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO ml_boosted_runs
                   (trade_date, et_time, source, lookback_days,
                    phit_n_samples, phit_n_hits, phit_n_misses, phit_base_rate,
                    phit_test_acc, phit_test_auc, phit_n_train, phit_n_test,
                    phit_importance,
                    range_n_samples, range_mean_excursion, range_median_excursion,
                    range_test_mae, range_test_coverage, range_importance,
                    selection_bias)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   RETURNING id""",
                (
                    now_et.date(), now_et.strftime("%H:%M"), source, days,
                    phit_metrics.get("n_samples"),
                    phit_metrics.get("n_hits"),
                    phit_metrics.get("n_misses"),
                    phit_metrics.get("base_rate"),
                    phit_metrics.get("test_acc"),
                    phit_metrics.get("test_auc"),
                    phit_metrics.get("n_train"),
                    phit_metrics.get("n_test"),
                    json.dumps(phit_metrics.get("feature_importance")),
                    (range_metrics or {}).get("n_samples"),
                    (range_metrics or {}).get("mean_excursion_pct"),
                    (range_metrics or {}).get("median_excursion_pct"),
                    json.dumps((range_metrics or {}).get("test_mae")),
                    json.dumps((range_metrics or {}).get("test_coverage")),
                    json.dumps((range_metrics or {}).get("feature_importance")),
                    json.dumps(bias) if bias else None,
                ),
            )
            run_id = cur.fetchone()[0]
        conn.commit()
        log.info("Saved boosted ML run #%d to ml_boosted_runs.", run_id)
        return run_id
    except Exception:
        conn.rollback()
        log.exception("Failed to save boosted ML run.")
        return None
    finally:
        conn.close()


def print_report(phit_m: dict, range_m: Optional[dict], source: str,
                 bias: Optional[dict]) -> None:
    bar = "=" * 74
    print(f"\n{bar}")
    print("GRADIENT-BOOSTED MODELS (LightGBM)")
    print(bar)
    print(f"\nData source   : {source}")
    print(f"\n── P(hit) classifier ──")
    print(f"Labeled rows  : {phit_m.get('n_samples')}  "
          f"({phit_m.get('n_hits')} hits / {phit_m.get('n_misses')} misses, "
          f"base {phit_m.get('base_rate')}%)")
    if bias and bias.get("pick_hit_rate") is not None:
        print(f"Selection bias: picks {bias['pick_hit_rate']}% "
              f"vs rejected {bias['nonpick_hit_rate']}%")
    print(f"Walk-forward  : test acc {phit_m.get('test_acc')}%  "
          f"AUC {phit_m.get('test_auc')}  "
          f"({phit_m.get('n_train')} train → {phit_m.get('n_test')} test)")
    print("Top features  :")
    for item in (phit_m.get("feature_importance") or [])[:8]:
        print(f"  {item['name']:<12} gain={item['gain']:.1f}")

    if range_m:
        print(f"\n── Price-range quantile model ──")
        print(f"Labeled rows  : {range_m.get('n_samples')}  "
              f"(mean excursion {range_m.get('mean_excursion_pct')}%, "
              f"median {range_m.get('median_excursion_pct')}%)")
        print(f"Walk-forward MAE (excursion fraction): {range_m.get('test_mae')}")
        print(f"Quantile coverage (ideal ≈ 0.25/0.50/0.75): "
              f"{range_m.get('test_coverage')}")
        print("Top features (median model):")
        for item in (range_m.get("feature_importance") or [])[:8]:
            print(f"  {item['name']:<12} gain={item['gain']:.1f}")
    print(f"\n{bar}")
    print(f"Artifacts: {PHIT_PATH.name}"
          + (f", {RANGE_PATH.name}" if range_m else ""))
    print(bar + "\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    _require_lgbm()

    parser = argparse.ArgumentParser(
        description="Train LightGBM P(hit) + price-range models "
                    "(alongside logistic Fib pipeline).",
    )
    parser.add_argument("--source", choices=["auto", "features", "picks"],
                        default="auto")
    parser.add_argument("--days", type=int, default=None)
    parser.add_argument("--min-samples", type=int, default=50)
    parser.add_argument("--test-frac", type=float, default=0.3)
    parser.add_argument("--save-db", action="store_true",
                        help="Log run to ml_boosted_runs for the dashboard")
    parser.add_argument("--no-regime", action="store_true")
    parser.add_argument("--no-range", action="store_true",
                        help="Skip the price-range quantile model")
    args = parser.parse_args(argv)

    try:
        picks, source = load_training_data(args.source, days=args.days,
                                           min_samples=args.min_samples)
    except Exception as e:
        print(f"ERROR: could not load training data — {e}")
        return 1

    if len(picks) < args.min_samples:
        print(f"Only {len(picks)} labeled rows (need >= {args.min_samples}).")
        return 1
    if sum(p.hit for p in picks) == 0 or sum(1 - p.hit for p in picks) == 0:
        print("Need both hits and misses to train the P(hit) classifier.")
        return 1

    regime = None if args.no_regime else load_spy_regime()
    X, names, _ = build_design_matrix(
        picks, regime=regime, include_context=True,
        include_regime=not args.no_regime,
    )
    y_hit = [p.hit for p in picks]

    phit_art, phit_m = train_phit(X, y_hit, names, test_frac=args.test_frac)
    phit_art["source"] = source
    phit_art["include_regime"] = not args.no_regime
    save_artifact(PHIT_PATH, phit_art)

    range_m = None
    if not args.no_range:
        # Only rows with a measurable favourable excursion.
        idx = [i for i, p in enumerate(picks) if p.favorable_excursion is not None]
        if len(idx) >= args.min_samples:
            import numpy as np
            Xr = np.asarray(X, dtype=float)[idx]
            yr = [picks[i].favorable_excursion for i in idx]
            range_art, range_m = train_range(Xr, yr, names, test_frac=args.test_frac)
            range_art["source"] = source
            range_art["include_regime"] = not args.no_regime
            save_artifact(RANGE_PATH, range_art)
        else:
            log.warning("Only %d rows with window extremes — skipping range model.",
                        len(idx))

    bias = selection_bias(picks) if source == "features" else None
    print_report(phit_m, range_m, source, bias)

    if args.save_db:
        save_run(source=source, days=args.days, phit_metrics=phit_m,
                 range_metrics=range_m, bias=bias)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
