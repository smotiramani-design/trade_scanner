"""
backtest/logistic_tuner.py — Learn conviction weights from labeled picks.

This is the machine-learning upgrade to weight_tuner.py. Instead of the
win/loss-alignment *heuristic*, it fits an L2-regularised logistic regression
that predicts whether a pick's Fibonacci target was hit (picks.fib_hit) from the
10-signal vector, then turns the learned coefficients into conviction weights.

Plain-English version:
  Every past pick recorded (a) what each of the 10 signals said and (b) whether
  the trade's target actually got hit. This reads all of those, figures out how
  much to trust each signal (turns a dial up or down per signal), and writes the
  new dials into signals/conviction.py. Re-run it weekly as more labeled picks
  pile up in Supabase and the weights keep adapting.

Where the data comes from:
  The `picks` table in Postgres/Supabase. A pick is "labeled" once the 4 PM Fib
  validation job has set `fib_hit` (True = target hit, False = missed). Signals
  are read from the `signals` JSONB column ({name: {bias, label}}).

Feature encoding (per signal, relative to the pick's own direction):
  +1  signal agreed with the trade direction
  -1  signal disagreed
   0  neutral / missing
So a positive learned coefficient means "when this signal agrees, hit-rate goes
up" → higher weight. A near-zero coefficient means the signal barely matters.

Usage:
  # Report only (does not touch conviction.py):
  python -m backtest.logistic_tuner

  # Only use the last 30 days of labeled picks:
  python -m backtest.logistic_tuner --days 30

  # Learn AND write the new weights into signals/conviction.py:
  python -m backtest.logistic_tuner --apply

Requires DATABASE_URL to be set (same Supabase URL used by the scanner) and
scikit-learn + psycopg installed (see requirements.txt).

IMPORTANT — no lookahead: evaluation uses a time-ordered split (train on older
picks, test on newer ones), never a random split, so the reported test accuracy
is an honest estimate of forward performance rather than a fooled-by-the-future
number.
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from signals import SIG_NAMES
from backtest.weight_tuner import CURRENT_WEIGHTS, apply_weights

log = logging.getLogger(__name__)
N_SIGNALS = len(SIG_NAMES)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class LabeledPick:
    direction:  str          # "bull" | "bear"
    features:   List[int]    # aligned encoding per signal: +1 / -1 / 0
    hit:        int          # 1 = fib target hit, 0 = missed
    trade_date: str          # ET calendar day (for chronological ordering)
    et_time:    str          # ET HH:MM (for chronological ordering)


def _aligned(bias: Optional[str], direction: str) -> int:
    """Encode one signal relative to the pick's trade direction."""
    if bias not in ("bull", "bear"):
        return 0
    return 1 if bias == direction else -1


def _features_from_signals(signals: dict, direction: str) -> List[int]:
    """Build the 10-dim aligned feature vector from a picks.signals JSONB dict."""
    feats: List[int] = []
    for name in SIG_NAMES:
        entry = signals.get(name) if isinstance(signals, dict) else None
        bias = entry.get("bias") if isinstance(entry, dict) else None
        feats.append(_aligned(bias, direction))
    return feats


# ── Load labeled picks from Supabase ──────────────────────────────────────────

def _connect():
    if not config.DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set — cannot read picks from Supabase.\n"
            "Set it in .env (Supabase → Settings → Database → Connection string)."
        )
    import psycopg  # lazy import so the rest of the repo works without the driver
    return psycopg.connect(config.DATABASE_URL)


def load_labeled_picks(days: Optional[int] = None, conn=None) -> List[LabeledPick]:
    """
    Read every pick with a resolved fib_hit label from Postgres/Supabase.

    days: if given, only include picks whose trade_date is within the last N days.
    """
    import json

    own = conn is None
    conn = conn or _connect()
    try:
        where = ("WHERE fib_hit IS NOT NULL "
                 "AND signals IS NOT NULL "
                 "AND direction IS NOT NULL")
        params: list = []
        if days:
            where += " AND trade_date >= (CURRENT_DATE - %s::int)"
            params.append(int(days))
        sql = (f"SELECT direction, signals, fib_hit, trade_date, et_time "
               f"FROM picks {where} "
               f"ORDER BY trade_date, et_time, id")
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        if own:
            conn.close()

    picks: List[LabeledPick] = []
    for direction, signals, fib_hit, trade_date, et_time in rows:
        if isinstance(signals, str):          # jsonb usually arrives as dict already
            try:
                signals = json.loads(signals)
            except (ValueError, TypeError):
                signals = {}
        picks.append(LabeledPick(
            direction  = direction,
            features   = _features_from_signals(signals or {}, direction),
            hit        = 1 if fib_hit else 0,
            trade_date = str(trade_date),
            et_time    = et_time or "",
        ))
    log.info("Loaded %d labeled picks from Supabase.", len(picks))
    return picks


# ── Model fit ─────────────────────────────────────────────────────────────────

@dataclass
class FitResult:
    coefs:      List[float]
    intercept:  float
    n_samples:  int
    n_hits:     int
    n_misses:   int
    train_acc:  float
    test_acc:   Optional[float]
    test_auc:   Optional[float]
    n_train:    int
    n_test:     int


def fit_logreg(
    picks:     Sequence[LabeledPick],
    C:         float = 1.0,
    test_frac: float = 0.3,
) -> FitResult:
    """
    Fit L2 logistic regression predicting hit (1) vs miss (0) from the aligned
    signal vector. Returns coefficients plus a walk-forward test score.
    """
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, roc_auc_score

    X = np.asarray([p.features for p in picks], dtype=float)
    y = np.asarray([p.hit for p in picks], dtype=int)
    n = int(len(y))
    n_hits = int(y.sum())
    n_misses = n - n_hits

    def _new_model() -> "LogisticRegression":
        return LogisticRegression(
            penalty="l2", C=C, class_weight="balanced",
            solver="liblinear", max_iter=1000,
        )

    # Walk-forward evaluation: train on older picks, test on newer ones.
    test_acc: Optional[float] = None
    test_auc: Optional[float] = None
    n_train = n
    n_test = 0
    if n >= 20 and 0.0 < test_frac < 1.0 and n_hits > 0 and n_misses > 0:
        split = int(round(n * (1.0 - test_frac)))
        Xtr, Xte = X[:split], X[split:]
        ytr, yte = y[:split], y[split:]
        if len(set(ytr.tolist())) == 2 and len(yte) > 0:
            m = _new_model()
            m.fit(Xtr, ytr)
            n_train, n_test = int(len(ytr)), int(len(yte))
            test_acc = float(accuracy_score(yte, m.predict(Xte)))
            if len(set(yte.tolist())) == 2:
                test_auc = float(roc_auc_score(yte, m.predict_proba(Xte)[:, 1]))

    # Final model on ALL labeled data — this is what the shipped weights come from.
    model = _new_model()
    model.fit(X, y)
    coefs = [float(c) for c in model.coef_[0]]
    train_acc = float(accuracy_score(y, model.predict(X)))

    return FitResult(
        coefs=coefs, intercept=float(model.intercept_[0]),
        n_samples=n, n_hits=n_hits, n_misses=n_misses,
        train_acc=train_acc, test_acc=test_acc, test_auc=test_auc,
        n_train=n_train, n_test=n_test,
    )


# ── Coefficients → conviction weights ─────────────────────────────────────────

def coefs_to_weights(
    coefs:      Sequence[float],
    min_weight: float = 0.5,
    max_weight: float = 2.0,
) -> List[float]:
    """
    Map learned coefficients onto the conviction weight range.

    Highest-coefficient signal → max_weight, lowest → min_weight, linear between.
    Keeps the same scale/convention as the existing hand-tuned weights so the
    rest of the pipeline (conviction %, grades, trade gates) is unaffected.
    """
    coefs = list(coefs)
    if not coefs:
        return list(CURRENT_WEIGHTS)
    min_c, max_c = min(coefs), max(coefs)
    rng = (max_c - min_c) or 1.0
    weights = []
    for c in coefs:
        norm = (c - min_c) / rng
        weights.append(round(min_weight + norm * (max_weight - min_weight), 2))
    return weights


# ── Report ────────────────────────────────────────────────────────────────────

def print_report(fit: FitResult, new_weights: List[float]) -> None:
    bar = "=" * 74
    print(f"\n{bar}")
    print("LOGISTIC-REGRESSION CONVICTION WEIGHT LEARNING")
    print(bar)
    print(f"\nLabeled picks : {fit.n_samples}  "
          f"({fit.n_hits} hits / {fit.n_misses} misses, "
          f"base hit-rate {100 * fit.n_hits / fit.n_samples:.1f}%)"
          if fit.n_samples else "\nLabeled picks : 0")
    print(f"Train accuracy: {fit.train_acc * 100:.1f}%  (in-sample, all data)")
    if fit.test_acc is not None:
        auc = f"{fit.test_auc:.3f}" if fit.test_auc is not None else "n/a"
        print(f"Walk-forward  : test acc {fit.test_acc * 100:.1f}%  "
              f"AUC {auc}  ({fit.n_train} train → {fit.n_test} test, "
              f"time-ordered)")
    else:
        print("Walk-forward  : skipped (need >=20 picks with both hits & misses)")

    print(f"\n{'Signal':<10} {'Coef':>9} {'OldWeight':>10} "
          f"{'NewWeight':>10} {'Change':>9}")
    print("-" * 74)
    for i, name in enumerate(SIG_NAMES):
        coef = fit.coefs[i] if i < len(fit.coefs) else 0.0
        ow = CURRENT_WEIGHTS[i] if i < len(CURRENT_WEIGHTS) else 1.0
        nw = new_weights[i] if i < len(new_weights) else ow
        print(f"{name:<10} {coef:>+9.4f} {ow:>10.2f} {nw:>10.2f} {nw - ow:>+9.2f}")

    print(f"\n{bar}")
    print("NEW WEIGHTS — paste into signals/conviction.py (or re-run with --apply):")
    print(bar)
    fmt = ", ".join(str(w) for w in new_weights)
    print(f"\nWEIGHTS: List[float] = [{fmt}]")
    print(f"MAX_WEIGHTED = sum(WEIGHTS)   # {sum(new_weights):.1f}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(
        description="Learn conviction weights from labeled Supabase picks "
                    "using L2 logistic regression.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m backtest.logistic_tuner
  python -m backtest.logistic_tuner --days 30
  python -m backtest.logistic_tuner --apply
  python -m backtest.logistic_tuner --days 60 --min-samples 40 --apply
        """,
    )
    parser.add_argument("--days", type=int, default=None,
                        help="Only use picks from the last N days (default: all)")
    parser.add_argument("--apply", action="store_true",
                        help="Write learned weights into signals/conviction.py")
    parser.add_argument("--min-samples", type=int, default=30,
                        help="Minimum labeled picks required to trust the fit")
    parser.add_argument("--min-weight", type=float, default=0.5)
    parser.add_argument("--max-weight", type=float, default=2.0)
    parser.add_argument("--C", type=float, default=1.0,
                        help="Inverse L2 strength (smaller = more regularisation)")
    parser.add_argument("--test-frac", type=float, default=0.3,
                        help="Fraction of newest picks held out for walk-forward test")
    args = parser.parse_args(argv)

    try:
        picks = load_labeled_picks(days=args.days)
    except Exception as e:
        print(f"ERROR: could not load picks — {e}")
        return 1

    if not picks:
        print("No labeled picks found. Let the 4 PM Fib validation run for a few "
              "days first (picks need fib_hit set), then re-run this.")
        return 1

    n = len(picks)
    n_hits = sum(p.hit for p in picks)
    n_misses = n - n_hits

    if n < args.min_samples:
        print(f"Only {n} labeled picks (need >= {args.min_samples}). "
              f"Reporting anyway, but NOT applying — too little data to trust.")
    if n_hits == 0 or n_misses == 0:
        only = "hits" if n_misses == 0 else "misses"
        print(f"All {n} labeled picks are {only}; cannot learn from a single "
              f"class yet. Keeping current weights.")
        return 1

    fit = fit_logreg(picks, C=args.C, test_frac=args.test_frac)
    new_weights = coefs_to_weights(fit.coefs,
                                   min_weight=args.min_weight,
                                   max_weight=args.max_weight)
    print_report(fit, new_weights)

    if args.apply:
        if n < args.min_samples:
            print("Refusing to --apply with insufficient data "
                  f"({n} < {args.min_samples}). Re-run once more picks are labeled.")
            return 1
        apply_weights(new_weights)
    else:
        print("Tip: re-run with --apply to write these weights to conviction.py.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
