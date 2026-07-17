"""
backtest/logistic_tuner.py — Learn conviction weights from labeled picks.

Machine-learning upgrade to weight_tuner.py. It fits an L2-regularised logistic
regression that predicts whether a pick's Fibonacci target was hit
(picks.fib_hit) and turns the learned coefficients into conviction weights.

Plain-English version:
  Every past pick recorded (a) what each of the 10 signals said, (b) some
  context (conviction, time of day, earnings, volatility), and — now — (c) what
  the broader market was doing that day. This reads all of it, figures out how
  much to trust each signal *given that context*, and writes the new signal dials
  into signals/conviction.py. Re-run weekly as more labeled picks accumulate.

── Feature enrichment (step #1) ───────────────────────────────────────────────
The model no longer sees only 10 crude flags. It also gets:

  Context (from the picks table, free):
    conviction, mtf_aligned, earnings_soon, time-of-day, |chg%|, ATR stop-distance
  Market regime (reconstructed from SPY daily bars, direction-signed):
    trend (SPY vs its 20-day SMA), 5-day momentum, realised volatility

Why this matters: a bullish setup in a rallying market and the same setup in a
sell-off used to be identical inputs. Regime tells the model which way the wind
is blowing. The regime/context features are direction-signed where relevant so a
positive value always means "this favours the trade".

── Important: only the 10 signal weights are written back ──────────────────────
The context + regime features are included as **statistical controls**. Adding
them makes the estimate of each *signal's* weight more accurate (it removes
omitted-variable bias — e.g. crediting a signal for wins that were really just a
strong market). But only the first 10 coefficients (the signals) are mapped to
conviction weights and written to conviction.py; the context coefficients are
reported for insight and set up the future "rank by P(hit)" step. This keeps the
rest of the pipeline (conviction %, grades, trade gates) unchanged.

── Training data source (step #2 — selection-bias fix) ─────────────────────────
By default this trains on `scan_features` — the FULL scanned universe, including
the tickers the scanner rejected — not just the surfaced top picks. Training on
picks-only was biased: the model never saw the rejected setups, so it couldn't
learn what separates good from bad. `--source` controls this:
  auto      (default) use scan_features if it has enough labeled rows, else picks
  features  force the de-biased universe
  picks     force top-picks only (legacy behaviour)
When training on features, the report also shows the selection-bias gap (hit rate
of picks vs rejected names).

Usage:
  python -m backtest.logistic_tuner                    # report only, all data
  python -m backtest.logistic_tuner --days 30          # last 30 days
  python -m backtest.logistic_tuner --apply --save-db  # write weights + log run
  python -m backtest.logistic_tuner --source picks     # legacy picks-only
  python -m backtest.logistic_tuner --no-regime        # skip SPY fetch (no network)

--save-db writes the run (weights, metrics, coefficients) to ml_weight_runs so the
dashboard's Machine Learning tab can display it.

--apply also serializes the trained model to models/phit_model.json (or pass
--save-model without --apply). At scan time signals/phit.py loads that artifact and
ranks the surfaced picks by the model's predicted probability of hitting the Fib
target — using the FULL model (signals + context + regime), not just the 10 signal
weights. This is the "rank by P(hit)" step the weight-mapping was a stepping stone to.

Requires DATABASE_URL set and scikit-learn + psycopg installed (requirements.txt).
Market regime fetches SPY daily bars (needs network); use --no-regime to skip.

No lookahead: evaluation uses a time-ordered split (train on older rows, test on
newer). Regime for a row's day uses SPY data from the *prior* session only.
"""
from __future__ import annotations

import argparse
import bisect
import logging
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from signals import SIG_NAMES
from backtest.weight_tuner import CURRENT_WEIGHTS, apply_weights

log = logging.getLogger(__name__)
N_SIGNALS = len(SIG_NAMES)

CONTEXT_NAMES = ["conviction", "mtf_align", "earnings", "et_hour", "abs_chg", "atr_pct"]
REGIME_NAMES = ["mkt_trend", "mkt_mom", "mkt_vol"]

# Where the serialized P(hit) model lives. Read at scan time by signals/phit.py to
# rank picks by predicted probability. Plain JSON (no pickle) so it's safe,
# versionable, and needs no sklearn/numpy to load or predict.
MODEL_PATH = Path(__file__).parent.parent / "models" / "phit_model.json"


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class LabeledPick:
    direction:     str            # "bull" | "bear"
    signals_feat:  List[int]      # 10 aligned signal values: +1 / -1 / 0
    hit:           int            # 1 = fib target hit, 0 = missed
    trade_date:    Optional[date] # ET calendar day (for regime lookup + ordering)
    et_time:       str            # ET HH:MM (for ordering + time-of-day feature)
    conviction:    float = 0.0
    mtf_aligned:   int = 1
    earnings_soon: int = 0
    chg_pct:       float = 0.0
    atr_stop:      Optional[float] = None
    price:         Optional[float] = None
    was_pick:      Optional[bool] = None  # scan_features only: made the top-N?

    @property
    def dir_sign(self) -> float:
        return 1.0 if self.direction == "bull" else -1.0


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


# ── Market regime (reconstructed from SPY daily bars) ─────────────────────────

class RegimeLookup:
    """Per-day SPY regime: (trend, momentum, volatility), read as of the prior day."""

    def __init__(self, by_date: dict):
        self._dates: List[date] = sorted(by_date)
        self._map = by_date

    def for_date(self, d: Optional[date]) -> Tuple[float, float, float]:
        """Regime as of the last SPY session strictly before d (no lookahead)."""
        if d is None or not self._dates:
            return (0.0, 0.0, 0.0)
        i = bisect.bisect_left(self._dates, d)
        if i == 0:
            return (0.0, 0.0, 0.0)
        return self._map[self._dates[i - 1]]


def load_spy_regime() -> Optional[RegimeLookup]:
    """Fetch SPY daily bars and compute per-day trend / momentum / volatility."""
    try:
        from data.yahoo_client import get_bars
        bars = get_bars("SPY", market_open=False)
    except Exception as e:  # network or driver issues — degrade gracefully
        log.warning("Could not fetch SPY bars for regime (%s). Continuing without.", e)
        return None

    bars = [b for b in bars if getattr(b, "close", None)]
    bars.sort(key=lambda b: b.timestamp)
    if len(bars) < 25:
        log.warning("Too few SPY bars (%d) to build regime. Continuing without.", len(bars))
        return None

    closes = [b.close for b in bars]
    dates = [b.timestamp.date() for b in bars]
    by_date: dict = {}
    for i in range(len(bars)):
        if i < 20:
            continue
        sma20 = sum(closes[i - 19:i + 1]) / 20.0
        trend = (closes[i] - sma20) / sma20 if sma20 else 0.0
        mom5 = (closes[i] / closes[i - 5] - 1.0) if closes[i - 5] else 0.0
        rets = [closes[j] / closes[j - 1] - 1.0
                for j in range(i - 9, i + 1) if closes[j - 1]]
        vol = statistics.pstdev(rets) if len(rets) > 1 else 0.0
        by_date[dates[i]] = (trend, mom5, vol)

    log.info("Built SPY regime for %d sessions.", len(by_date))
    return RegimeLookup(by_date) if by_date else None


# ── Load labeled picks from Supabase ──────────────────────────────────────────

def _connect():
    if not config.DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set — cannot read picks from Supabase.\n"
            "Set it in .env (Supabase → Settings → Database → Connection string)."
        )
    import psycopg  # lazy import so the rest of the repo works without the driver
    return psycopg.connect(config.DATABASE_URL)


def _load_labeled(table: str, days: Optional[int], conn) -> List[LabeledPick]:
    """Shared loader for the picks and scan_features tables (identical columns)."""
    import json

    own = conn is None
    conn = conn or _connect()
    with_pick = table == "scan_features"
    try:
        where = ("WHERE fib_hit IS NOT NULL "
                 "AND signals IS NOT NULL "
                 "AND direction IS NOT NULL")
        params: list = []
        if days:
            where += " AND trade_date >= (CURRENT_DATE - %s::int)"
            params.append(int(days))
        cols = ("direction, signals, fib_hit, trade_date, et_time, "
                "conviction, mtf_aligned, earnings_soon, chg_pct, atr_stop, price")
        if with_pick:
            cols += ", was_pick"
        sql = (f"SELECT {cols} FROM {table} {where} "
               f"ORDER BY trade_date, et_time, id")
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        if own:
            conn.close()

    picks: List[LabeledPick] = []
    for row in rows:
        (direction, signals, fib_hit, trade_date, et_time,
         conviction, mtf_aligned, earnings_soon, chg_pct, atr_stop, price) = row[:11]
        was_pick = bool(row[11]) if with_pick else None
        if isinstance(signals, str):
            try:
                signals = json.loads(signals)
            except (ValueError, TypeError):
                signals = {}
        picks.append(LabeledPick(
            direction     = direction,
            signals_feat  = _features_from_signals(signals or {}, direction),
            hit           = 1 if fib_hit else 0,
            trade_date    = trade_date if isinstance(trade_date, date) else None,
            et_time       = et_time or "",
            conviction    = float(conviction) if conviction is not None else 0.0,
            mtf_aligned   = 1 if (mtf_aligned in (True, None)) else 0,
            earnings_soon = 1 if earnings_soon else 0,
            chg_pct       = float(chg_pct) if chg_pct is not None else 0.0,
            atr_stop      = float(atr_stop) if atr_stop is not None else None,
            price         = float(price) if price is not None else None,
            was_pick      = was_pick,
        ))
    log.info("Loaded %d labeled rows from %s.", len(picks), table)
    return picks


def load_labeled_picks(days: Optional[int] = None, conn=None) -> List[LabeledPick]:
    """Read every top-N pick with a resolved fib_hit label."""
    return _load_labeled("picks", days, conn)


def load_labeled_features(days: Optional[int] = None, conn=None) -> List[LabeledPick]:
    """Read the full labeled scanned universe (de-biased training set)."""
    return _load_labeled("scan_features", days, conn)


def load_training_data(
    source: str = "auto",
    days:   Optional[int] = None,
    min_samples: int = 30,
) -> Tuple[List[LabeledPick], str]:
    """
    Resolve the training source and load it.

    source="auto": prefer the de-biased scan_features; fall back to picks if the
    universe log is empty/missing or has too few labeled rows.
    Returns (picks, resolved_source).
    """
    if source == "picks":
        return load_labeled_picks(days), "picks"
    if source == "features":
        return load_labeled_features(days), "features"

    # auto
    try:
        feats = load_labeled_features(days)
    except Exception as e:
        log.info("scan_features unavailable (%s) — using picks.", e)
        return load_labeled_picks(days), "picks"
    if len(feats) >= min_samples:
        return feats, "features"
    log.info("Only %d labeled scan_features rows (< %d) — using picks instead.",
             len(feats), min_samples)
    return load_labeled_picks(days), "picks"


# ── Design matrix (signals + context + regime) ────────────────────────────────

def _et_hour(et_time: str) -> float:
    try:
        return float(et_time.split(":")[0])
    except (ValueError, AttributeError, IndexError):
        return 12.0


def feature_names(include_context: bool = True, include_regime: bool = True) -> List[str]:
    """The design-matrix column names for a given feature configuration."""
    names: List[str] = list(SIG_NAMES)
    if include_context:
        names += CONTEXT_NAMES
    if include_regime:
        names += REGIME_NAMES
    return names


def row_for_pick(
    p:               LabeledPick,
    regime_tuple:    Optional[Tuple[float, float, float]],
    include_context: bool = True,
    include_regime:  bool = True,
) -> List[float]:
    """
    Build one design-matrix row (pure Python — no numpy).

    Shared by training (build_design_matrix) and live inference (signals/phit.py)
    so the two can never drift. regime_tuple is the (trend, mom, vol) for this
    pick's day; pass None to omit the regime block.
    """
    row: List[float] = [float(v) for v in p.signals_feat]
    if include_context:
        atr_pct = 0.0
        if p.atr_stop and p.price and p.price > 0:
            atr_pct = abs(p.price - p.atr_stop) / p.price
        row += [
            p.conviction,
            float(p.mtf_aligned),
            float(p.earnings_soon),
            _et_hour(p.et_time),
            abs(p.chg_pct),
            atr_pct,
        ]
    if include_regime and regime_tuple is not None:
        trend, mom, vol = regime_tuple
        # direction-sign the directional pieces: positive = market favours trade
        row += [trend * p.dir_sign, mom * p.dir_sign, vol]
    return row


def build_design_matrix(
    picks:           Sequence[LabeledPick],
    regime:          Optional[RegimeLookup] = None,
    include_context: bool = True,
    include_regime:  bool = True,
):
    """Return (X, feature_names, n_signal_cols). Columns 0..9 are the signals."""
    import numpy as np

    reg_ok = include_regime and regime is not None
    names = feature_names(include_context=include_context, include_regime=reg_ok)

    rows: List[List[float]] = []
    for p in picks:
        reg_tuple = regime.for_date(p.trade_date) if reg_ok else None
        rows.append(row_for_pick(p, reg_tuple,
                                 include_context=include_context,
                                 include_regime=reg_ok))

    X = np.asarray(rows, dtype=float)
    return X, names, N_SIGNALS


# ── Model fit ─────────────────────────────────────────────────────────────────

@dataclass
class FitResult:
    feature_names: List[str]
    coefs:         List[float]
    intercept:     float
    n_signal_cols: int
    n_samples:     int
    n_hits:        int
    n_misses:      int
    train_acc:     float
    test_acc:      Optional[float]
    test_auc:      Optional[float]
    n_train:       int
    n_test:        int
    # Full-data standardization for the context/regime columns (index >=
    # n_signal_cols). Needed to reproduce predictions at inference time.
    context_mean:  Optional[List[float]] = None
    context_std:   Optional[List[float]] = None

    @property
    def signal_coefs(self) -> List[float]:
        return self.coefs[:self.n_signal_cols]

    @property
    def context_coefs(self) -> List[Tuple[str, float]]:
        return list(zip(self.feature_names[self.n_signal_cols:],
                        self.coefs[self.n_signal_cols:]))


def _zscore_params(block):
    import numpy as np
    mean = block.mean(axis=0)
    std = block.std(axis=0)
    std = np.where(std == 0, 1.0, std)
    return mean, std


def fit_logreg(
    X,
    y,
    feature_names: List[str],
    n_signal_cols: int = N_SIGNALS,
    C:             float = 1.0,
    test_frac:     float = 0.3,
) -> FitResult:
    """
    Fit L2 logistic regression predicting hit (1) vs miss (0). Context columns
    (index >= n_signal_cols) are standardised; the 10 signal columns are left as
    raw +1/-1/0 so their coefficients map cleanly onto conviction weights.
    """
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, roc_auc_score

    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=int)
    n = int(len(y))
    n_hits = int(y.sum())
    n_misses = n - n_hits
    has_context = X.shape[1] > n_signal_cols

    def _std_apply(Xtr, Xte):
        if not has_context:
            return Xtr, Xte
        mean, std = _zscore_params(Xtr[:, n_signal_cols:])
        Xtr = Xtr.copy(); Xte = Xte.copy()
        Xtr[:, n_signal_cols:] = (Xtr[:, n_signal_cols:] - mean) / std
        Xte[:, n_signal_cols:] = (Xte[:, n_signal_cols:] - mean) / std
        return Xtr, Xte

    def _model():
        return LogisticRegression(penalty="l2", C=C, class_weight="balanced",
                                  solver="liblinear", max_iter=1000)

    # Walk-forward evaluation: older picks train, newer picks test.
    test_acc = test_auc = None
    n_train, n_test = n, 0
    if n >= 20 and 0.0 < test_frac < 1.0 and n_hits > 0 and n_misses > 0:
        split = int(round(n * (1.0 - test_frac)))
        Xtr, Xte = X[:split], X[split:]
        ytr, yte = y[:split], y[split:]
        if len(set(ytr.tolist())) == 2 and len(yte) > 0:
            Xtr_s, Xte_s = _std_apply(Xtr, Xte)
            m = _model()
            m.fit(Xtr_s, ytr)
            n_train, n_test = int(len(ytr)), int(len(yte))
            test_acc = float(accuracy_score(yte, m.predict(Xte_s)))
            if len(set(yte.tolist())) == 2:
                test_auc = float(roc_auc_score(yte, m.predict_proba(Xte_s)[:, 1]))

    # Final model on ALL data — this is where the shipped weights come from.
    # Capture the full-data context standardization so inference can reproduce it.
    ctx_mean = ctx_std = None
    if has_context:
        m, s = _zscore_params(X[:, n_signal_cols:])
        ctx_mean, ctx_std = m.tolist(), s.tolist()
    X_all, _ = _std_apply(X, X)
    model = _model()
    model.fit(X_all, y)
    coefs = [float(c) for c in model.coef_[0]]
    train_acc = float(accuracy_score(y, model.predict(X_all)))

    return FitResult(
        feature_names=list(feature_names), coefs=coefs,
        intercept=float(model.intercept_[0]), n_signal_cols=n_signal_cols,
        n_samples=n, n_hits=n_hits, n_misses=n_misses, train_acc=train_acc,
        test_acc=test_acc, test_auc=test_auc, n_train=n_train, n_test=n_test,
        context_mean=ctx_mean, context_std=ctx_std,
    )


# ── Coefficients → conviction weights ─────────────────────────────────────────

def coefs_to_weights(
    signal_coefs: Sequence[float],
    min_weight:   float = 0.5,
    max_weight:   float = 2.0,
) -> List[float]:
    """Map the 10 signal coefficients onto the conviction weight range."""
    coefs = list(signal_coefs)
    if not coefs:
        return list(CURRENT_WEIGHTS)
    min_c, max_c = min(coefs), max(coefs)
    rng = (max_c - min_c) or 1.0
    return [round(min_weight + (c - min_c) / rng * (max_weight - min_weight), 2)
            for c in coefs]


# ── Selection-bias stats (features source only) ───────────────────────────────

def selection_bias(picks: Sequence[LabeledPick]) -> Optional[dict]:
    """
    Compare hit rate of surfaced picks vs the rejected universe.

    Only meaningful when training on scan_features (was_pick is set). A large gap
    is exactly why training on picks-only was biased: the model never saw the
    rejected setups. Returns None if was_pick isn't available.
    """
    labeled = [p for p in picks if p.was_pick is not None]
    if not labeled:
        return None
    picked = [p for p in labeled if p.was_pick]
    rest = [p for p in labeled if not p.was_pick]

    def _rate(rows):
        return round(100.0 * sum(r.hit for r in rows) / len(rows), 1) if rows else None

    return {
        "n_pick": len(picked),
        "n_nonpick": len(rest),
        "pick_hit_rate": _rate(picked),
        "nonpick_hit_rate": _rate(rest),
    }


# ── Persist a run to Supabase (powers the dashboard ML tab) ───────────────────

def save_run(
    fit:            FitResult,
    new_weights:    List[float],
    *,
    source:         str,
    days:           Optional[int],
    use_regime:     bool,
    use_context:    bool,
    c_param:        float,
    applied:        bool,
    bias:           Optional[dict],
    conn=None,
) -> Optional[int]:
    """Insert one ml_weight_runs row. Returns the new id, or None if DB off."""
    import json
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    if not config.DB_ENABLED:
        log.warning("DB disabled — not saving ML run.")
        return None

    et = ZoneInfo("America/New_York")
    now_et = datetime.now(timezone.utc).astimezone(et)
    base_rate = round(100.0 * fit.n_hits / fit.n_samples, 1) if fit.n_samples else None

    weights_json = [
        {"signal": SIG_NAMES[i],
         "old": CURRENT_WEIGHTS[i] if i < len(CURRENT_WEIGHTS) else 1.0,
         "new": new_weights[i] if i < len(new_weights) else None,
         "coef": round(fit.signal_coefs[i], 4) if i < len(fit.signal_coefs) else None}
        for i in range(len(SIG_NAMES))
    ]
    context_json = [{"name": n, "coef": round(c, 4)} for n, c in fit.context_coefs]

    from utils.db_writer import init_db
    own = conn is None
    conn = conn or _connect()
    try:
        init_db(conn)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO ml_weight_runs
                   (trade_date, et_time, source, lookback_days, n_samples, n_hits,
                    n_misses, base_rate, train_acc, test_acc, test_auc, n_train,
                    n_test, use_regime, use_context, c_param, applied, weights,
                    context_coefs, selection_bias)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   RETURNING id""",
                (now_et.date(), now_et.strftime("%H:%M"), source, days,
                 fit.n_samples, fit.n_hits, fit.n_misses, base_rate,
                 round(fit.train_acc * 100, 1),
                 round(fit.test_acc * 100, 1) if fit.test_acc is not None else None,
                 round(fit.test_auc, 4) if fit.test_auc is not None else None,
                 fit.n_train, fit.n_test, use_regime, use_context, c_param, applied,
                 json.dumps(weights_json), json.dumps(context_json),
                 json.dumps(bias) if bias else None),
            )
            run_id = cur.fetchone()[0]
        conn.commit()
        log.info("Saved ML run #%d to ml_weight_runs.", run_id)
        return run_id
    except Exception:
        conn.rollback()
        log.exception("Failed to save ML run.")
        return None
    finally:
        if own:
            conn.close()


# ── Persist the trained model for live P(hit) scoring ─────────────────────────

def save_model(
    fit:             FitResult,
    *,
    source:          str,
    include_context: bool,
    include_regime:  bool,
    path:            Optional[Path] = None,
) -> Optional[Path]:
    """
    Serialize the full fitted model to JSON so the scanner can rank picks by
    predicted P(hit). Stores coefficients, intercept, the exact feature layout,
    and the context standardization params. Only the final all-data model is
    saved (this is the one whose weights ship).
    """
    import json
    from datetime import datetime, timezone

    path = path or MODEL_PATH
    base_rate = (fit.n_hits / fit.n_samples) if fit.n_samples else None
    artifact = {
        "version":         1,
        "trained_at":      datetime.now(timezone.utc).isoformat(),
        "source":          source,
        "n_samples":       fit.n_samples,
        "test_auc":        fit.test_auc,
        "base_rate":       round(base_rate, 4) if base_rate is not None else None,
        "feature_names":   fit.feature_names,
        "n_signal_cols":   fit.n_signal_cols,
        "coefs":           fit.coefs,
        "intercept":       fit.intercept,
        "context_mean":    fit.context_mean,
        "context_std":     fit.context_std,
        "include_context": include_context,
        "include_regime":  include_regime,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(artifact, indent=2))
        log.info("Saved P(hit) model to %s", path)
        return path
    except OSError:
        log.exception("Failed to write P(hit) model artifact.")
        return None


# ── Report ────────────────────────────────────────────────────────────────────

def print_report(fit: FitResult, new_weights: List[float],
                 source: str = "picks", bias: Optional[dict] = None) -> None:
    bar = "=" * 74
    print(f"\n{bar}")
    print("LOGISTIC-REGRESSION CONVICTION WEIGHT LEARNING")
    print(bar)
    src_label = ("full scanned universe (de-biased)" if source == "features"
                 else "top picks only")
    print(f"\nData source   : {source}  — {src_label}")
    if fit.n_samples:
        base = 100 * fit.n_hits / fit.n_samples
        print(f"Labeled rows  : {fit.n_samples}  "
              f"({fit.n_hits} hits / {fit.n_misses} misses, base {base:.1f}%)")
    else:
        print("Labeled rows  : 0")
    if bias and bias.get("pick_hit_rate") is not None:
        print(f"Selection bias: picks {bias['pick_hit_rate']}% "
              f"(n={bias['n_pick']}) vs rejected {bias['nonpick_hit_rate']}% "
              f"(n={bias['n_nonpick']})")
    n_ctx = len(fit.feature_names) - fit.n_signal_cols
    print(f"Features      : {fit.n_signal_cols} signals + {n_ctx} context/regime")
    print(f"Train accuracy: {fit.train_acc * 100:.1f}%  (in-sample, all data)")
    if fit.test_acc is not None:
        auc = f"{fit.test_auc:.3f}" if fit.test_auc is not None else "n/a"
        print(f"Walk-forward  : test acc {fit.test_acc * 100:.1f}%  AUC {auc}  "
              f"({fit.n_train} train → {fit.n_test} test, time-ordered)")
    else:
        print("Walk-forward  : skipped (need >=20 picks with both hits & misses)")

    print(f"\n{'Signal':<10} {'Coef':>9} {'OldWeight':>10} "
          f"{'NewWeight':>10} {'Change':>9}")
    print("-" * 74)
    for i, name in enumerate(SIG_NAMES):
        coef = fit.signal_coefs[i] if i < len(fit.signal_coefs) else 0.0
        ow = CURRENT_WEIGHTS[i] if i < len(CURRENT_WEIGHTS) else 1.0
        nw = new_weights[i] if i < len(new_weights) else ow
        print(f"{name:<10} {coef:>+9.4f} {ow:>10.2f} {nw:>10.2f} {nw - ow:>+9.2f}")

    if fit.context_coefs:
        print(f"\n{'Context/regime':<16} {'Coef':>9}   (insight only — not written to weights)")
        print("-" * 74)
        for name, coef in sorted(fit.context_coefs, key=lambda x: -abs(x[1])):
            arrow = "↑ helps" if coef > 0 else "↓ hurts" if coef < 0 else "—"
            print(f"{name:<16} {coef:>+9.4f}   {arrow}")

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
        description="Learn conviction weights from labeled Supabase picks using "
                    "L2 logistic regression with market-regime + context features.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m backtest.logistic_tuner
  python -m backtest.logistic_tuner --days 30
  python -m backtest.logistic_tuner --apply
  python -m backtest.logistic_tuner --no-regime --days 60 --apply
        """,
    )
    parser.add_argument("--source", choices=["auto", "features", "picks"],
                        default="auto",
                        help="Training data: 'features' = full de-biased universe, "
                             "'picks' = top-N only, 'auto' = features if available")
    parser.add_argument("--days", type=int, default=None,
                        help="Only use rows from the last N days (default: all)")
    parser.add_argument("--apply", action="store_true",
                        help="Write learned signal weights into signals/conviction.py")
    parser.add_argument("--save-db", action="store_true",
                        help="Persist this run to ml_weight_runs (for the dashboard)")
    parser.add_argument("--save-model", action="store_true",
                        help="Write the trained model to models/phit_model.json so the "
                             "scanner ranks picks by predicted P(hit). Implied by --apply.")
    parser.add_argument("--min-samples", type=int, default=30,
                        help="Minimum labeled rows required to trust the fit")
    parser.add_argument("--min-weight", type=float, default=0.5)
    parser.add_argument("--max-weight", type=float, default=2.0)
    parser.add_argument("--C", type=float, default=1.0,
                        help="Inverse L2 strength (smaller = more regularisation)")
    parser.add_argument("--test-frac", type=float, default=0.3,
                        help="Fraction of newest rows held out for walk-forward test")
    parser.add_argument("--no-context", action="store_true",
                        help="Drop the pick-context features")
    parser.add_argument("--no-regime", action="store_true",
                        help="Skip SPY market-regime features (avoids network fetch)")
    args = parser.parse_args(argv)

    try:
        picks, source = load_training_data(args.source, days=args.days,
                                           min_samples=args.min_samples)
    except Exception as e:
        print(f"ERROR: could not load training data — {e}")
        return 1

    if not picks:
        print("No labeled rows found. Let the 4 PM validation run for a few days "
              "first (rows need fib_hit set), then re-run this.")
        return 1

    n = len(picks)
    n_hits = sum(p.hit for p in picks)
    n_misses = n - n_hits

    if n < args.min_samples:
        print(f"Only {n} labeled rows (need >= {args.min_samples}). "
              f"Reporting anyway, but NOT applying — too little data to trust.")
    if n_hits == 0 or n_misses == 0:
        only = "hits" if n_misses == 0 else "misses"
        print(f"All {n} labeled rows are {only}; cannot learn from a single "
              f"class yet. Keeping current weights.")
        return 1

    regime = None if args.no_regime else load_spy_regime()
    X, names, n_sig = build_design_matrix(
        picks, regime=regime,
        include_context=not args.no_context,
        include_regime=not args.no_regime,
    )
    y = [p.hit for p in picks]

    fit = fit_logreg(X, y, names, n_signal_cols=n_sig,
                     C=args.C, test_frac=args.test_frac)
    new_weights = coefs_to_weights(fit.signal_coefs,
                                   min_weight=args.min_weight,
                                   max_weight=args.max_weight)
    bias = selection_bias(picks) if source == "features" else None
    print_report(fit, new_weights, source=source, bias=bias)

    applied = False
    if args.apply:
        if n < args.min_samples:
            print("Refusing to --apply with insufficient data "
                  f"({n} < {args.min_samples}). Re-run once more rows are labeled.")
        else:
            applied = apply_weights(new_weights)
    else:
        print("Tip: re-run with --apply to write these weights to conviction.py.")

    # Save the model for live P(hit) ranking whenever we applied (so weights and
    # model stay in lockstep) or the user asked for it explicitly with --save-model.
    if applied or args.save_model:
        p = save_model(fit, source=source,
                       include_context=not args.no_context,
                       include_regime=not args.no_regime)
        if p:
            print(f"\n✓ P(hit) model saved to {p}")
            print("  The scanner will now rank picks by predicted probability.")

    if args.save_db:
        save_run(fit, new_weights, source=source, days=args.days,
                 use_regime=not args.no_regime, use_context=not args.no_context,
                 c_param=args.C, applied=applied, bias=bias)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
