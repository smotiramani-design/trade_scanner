"""
utils/exporter.py — saves TickerAnalysis results to CSV / JSON.
Includes Fibonacci level columns when available.
"""
import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List

import config
from signals import SIG_NAMES   # single source of truth — auto-updates with signal count
from signals.base import TickerAnalysis

log = logging.getLogger(__name__)


def _row(ta: TickerAnalysis) -> dict:
    row = {
        "ticker":       ta.ticker,
        "company_name": ta.company_name,
        "sector":       getattr(ta, "sector", ""),
        "price":        round(ta.price, 2)   if ta.price   else "",
        "chg_pct":      round(ta.chg_pct, 2) if ta.chg_pct else "",
        "net_score":    ta.net_score,
        "bull":         ta.bull_count,
        "bear":         ta.bear_count,
        "verdict":      ta.verdict,
        "bars":         ta.bars,
        "mode":         ta.mode,
        "mtf_aligned":  getattr(ta, "mtf_aligned", ""),
        "mtf_detail":   getattr(ta, "mtf_detail",  ""),
        "earnings_soon":getattr(ta, "earnings_soon", ""),
        "atr_stop":     round(ta.atr_stop, 2) if getattr(ta, "atr_stop", None) else "",
    }
    for i, sig in enumerate(ta.signals):
        key = SIG_NAMES[i] if i < len(SIG_NAMES) else f"sig_{i}"
        row[key] = sig.bias.value
        row[f"{key}_label"] = sig.label

    # ── Greeks / options columns ───────────────────────────────────────────────
    gd = getattr(ta, "gamma_data", None)
    row["gamma_strike"]   = round(gd.nearest_strike, 2)   if gd and gd.nearest_strike   else ""
    row["gamma_value"]    = round(gd.nearest_gamma,  4)   if gd and gd.nearest_gamma    else ""
    row["gamma_oi"]       = gd.nearest_oi                 if gd and gd.nearest_oi       else ""
    row["gamma_pin"]      = "YES"                         if gd and gd.pin_risk          else ""
    row["gamma_squeeze"]  = "YES"                         if gd and gd.squeeze_setup     else ""
    row["gamma_size_mult"]= round(gd.size_multiplier, 2)  if gd                          else 1.0
    row["gamma_detail"]   = gd.detail                     if gd                          else ""

    # ── Fibonacci columns ─────────────────────────────────────────────────────
    if ta.fib:
        row.update(ta.fib.to_dict())
    else:
        row.update({
            "fib_anchor":       "",
            "fib_swing_high":   "",
            "fib_swing_low":    "",
            "fib_direction":    "",
            "fib_next_target":  "",
            "fib_next_label":   "",
            "fib_support_1":    "",
            "fib_resistance_1": "",
        })
    return row


def save_results(results: List[TickerAnalysis], tag: str = "") -> Path:
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"scan_{tag}_{ts}" if tag else f"scan_{ts}"
    saved = []

    if config.SAVE_CSV:
        path = config.OUTPUT_DIR / f"{stem}.csv"
        rows = [_row(ta) for ta in results]
        if rows:
            with open(path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            log.info("Saved CSV → %s", path)
            saved.append(path)

    if config.SAVE_JSON:
        path = config.OUTPUT_DIR / f"{stem}.json"
        with open(path, "w") as f:
            json.dump([_row(ta) for ta in results], f, indent=2)
        log.info("Saved JSON → %s", path)
        saved.append(path)

    return saved[0] if saved else config.OUTPUT_DIR
