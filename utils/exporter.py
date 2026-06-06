"""
utils/exporter.py — saves TickerAnalysis results to CSV / JSON.
"""
import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List

import config
from signals.base import TickerAnalysis

log = logging.getLogger(__name__)
SIG_NAMES = ["Candle", "Volume", "SMA", "Gaps", "Stoch", "CCI", "RR"]


def _row(ta: TickerAnalysis) -> dict:
    row = {
        "ticker":    ta.ticker,
        "price":     round(ta.price, 2)   if ta.price  else "",
        "chg_pct":   round(ta.chg_pct, 2) if ta.chg_pct else "",
        "net_score": ta.net_score,
        "bull":      ta.bull_count,
        "bear":      ta.bear_count,
        "verdict":   ta.verdict,
        "bars":      ta.bars,
        "mode":      ta.mode,
    }
    for i, sig in enumerate(ta.signals):
        key = SIG_NAMES[i] if i < len(SIG_NAMES) else f"sig_{i}"
        row[key] = sig.bias.value
        row[f"{key}_label"] = sig.label
    return row


def save_results(results: List[TickerAnalysis], tag: str = "") -> Path:
    ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem  = f"scan_{tag}_{ts}" if tag else f"scan_{ts}"
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
