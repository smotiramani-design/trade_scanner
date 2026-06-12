"""
backtest/weight_tuner.py — ENH-19: Signal weight auto-tuning.

Analyses backtest trade records to find which signals have the highest
correlation with winning trades, then outputs optimised conviction weights.

Algorithm:
  1. Load all trades from one or more backtest CSV files (ALL TRADES section)
  2. For each trade, look up which signals fired at entry (from the scan log
     or from re-running signals on the entry-date bars)
  3. For wins: count which signals were BULL/BEAR aligned with trade direction
  4. For losses: count which signals were BULL/BEAR aligned with trade direction
  5. Signal score = (aligned_wins / total_wins) - (aligned_losses / total_losses)
     → Signals that appear more in wins than losses get higher weight
  6. Normalise to match the original weight range (0.5 – 2.0)
  7. Output new WEIGHTS list to paste into conviction.py

Usage:
  python -m backtest.weight_tuner output/backtest_*.csv
  python -m backtest.weight_tuner output/backtest_20260611.csv --apply

--apply writes the new weights directly to signals/conviction.py.

Note: This requires re-running signals on each trade's entry-bar, which
means fetching 1-year of bars for each ticker in the backtest CSVs.
Use --quick for a statistical approximation without re-fetching bars.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from data.yahoo_client import get_bars, Bar
from signals import run_all, SIG_NAMES
from signals.base import Bias

log = logging.getLogger(__name__)

CURRENT_WEIGHTS = [1.5, 1.5, 1.0, 1.0, 1.2, 1.2, 1.6, 1.3, 1.1, 0.9]
N_SIGNALS = len(SIG_NAMES)


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class TradeEntry:
    ticker:    str
    side:      str
    entry_date: str
    exit_date:  str
    pnl_usd:   float
    is_win:    bool
    entry_bar: Optional[int] = None   # bar index in fetched bars


@dataclass
class SignalStats:
    name:         str
    aligned_wins: int = 0    # signal agreed with winning trade direction
    aligned_loss: int = 0    # signal agreed with losing trade direction
    total_wins:   int = 0
    total_losses: int = 0

    @property
    def win_rate_when_aligned(self) -> float:
        total = self.aligned_wins + self.aligned_loss
        return self.aligned_wins / total if total > 0 else 0.0

    @property
    def edge_score(self) -> float:
        """How much more this signal appears in wins than losses (normalised)."""
        win_pct  = self.aligned_wins / self.total_wins   if self.total_wins   > 0 else 0
        loss_pct = self.aligned_loss / self.total_losses if self.total_losses > 0 else 0
        return round(win_pct - loss_pct, 4)


# ── CSV parser ────────────────────────────────────────────────────────────────

def load_trades_from_csv(path: Path) -> List[TradeEntry]:
    """Parse the ALL TRADES section from a backtest CSV."""
    trades = []
    in_trades = False
    headers = []

    with open(path, newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            if row[0] == "# ALL TRADES":
                in_trades = True
                continue
            if in_trades and not headers:
                headers = row
                continue
            if in_trades and headers and len(row) == len(headers):
                d = dict(zip(headers, row))
                try:
                    pnl = float(d.get("pnl_usd", 0))
                    trades.append(TradeEntry(
                        ticker     = d.get("ticker", ""),
                        side       = d.get("side", "long"),
                        entry_date = d.get("entry_date", ""),
                        exit_date  = d.get("exit_date", ""),
                        pnl_usd    = pnl,
                        is_win     = pnl > 0,
                    ))
                except (ValueError, KeyError):
                    continue

    log.info("Loaded %d trades from %s", len(trades), path.name)
    return trades


# ── Signal re-computation ─────────────────────────────────────────────────────

def _find_entry_bar_idx(bars: List[Bar], entry_date: str) -> Optional[int]:
    """Find the bar index closest to the entry date."""
    from datetime import datetime
    try:
        target = datetime.fromisoformat(entry_date)
    except (ValueError, TypeError):
        return None
    for i, b in enumerate(bars):
        bar_date = b.timestamp
        if hasattr(bar_date, 'date'):
            bar_date = bar_date.date()
        try:
            t_date = target.date() if hasattr(target, 'date') else target
            if bar_date == t_date:
                return i
        except Exception:
            continue
    return None


def compute_signal_stats(
    trades: List[TradeEntry],
    window: int = 60,
    verbose: bool = False,
) -> List[SignalStats]:
    """
    For each trade, re-run signals on bars up to entry date and record
    which signals were aligned with the trade direction.
    """
    stats = [SignalStats(name=n) for n in SIG_NAMES]

    # Group trades by ticker to avoid fetching bars multiple times
    by_ticker: Dict[str, List[TradeEntry]] = defaultdict(list)
    for t in trades:
        by_ticker[t.ticker].append(t)

    total = len(by_ticker)
    for idx, (ticker, ticker_trades) in enumerate(by_ticker.items(), 1):
        print(f"  [{idx:3d}/{total}] {ticker:7s} ({len(ticker_trades)} trades)", end="\r", flush=True)
        bars = get_bars(ticker, market_open=False)
        if len(bars) < 35:
            continue

        for trade in ticker_trades:
            entry_idx = _find_entry_bar_idx(bars, trade.entry_date)
            if entry_idx is None or entry_idx < 30:
                continue

            # Re-run signals on bars up to entry (no lookahead)
            start = max(0, entry_idx - window)
            window_bars = bars[start: entry_idx + 1]
            if len(window_bars) < 30:
                continue

            try:
                sigs = run_all(window_bars, ticker=ticker)
            except Exception as e:
                log.debug("Signal re-run failed %s: %s", ticker, e)
                continue

            expected_bias = Bias.BULL if trade.side == "long" else Bias.BEAR

            for i, sig in enumerate(sigs):
                if i >= N_SIGNALS:
                    break
                aligned = sig.bias == expected_bias
                if trade.is_win:
                    stats[i].total_wins += 1
                    if aligned:
                        stats[i].aligned_wins += 1
                else:
                    stats[i].total_losses += 1
                    if aligned:
                        stats[i].aligned_loss += 1

    print()  # newline after carriage-return progress
    return stats


# ── Weight calculation ────────────────────────────────────────────────────────

def calc_new_weights(
    stats:       List[SignalStats],
    base_weight: float = 1.0,
    min_weight:  float = 0.3,
    max_weight:  float = 2.5,
    min_trades:  int   = 10,
) -> List[float]:
    """
    Convert edge scores into normalised weights.

    Signals with too few trades keep their current weight.
    Edge score range maps to [min_weight, max_weight].
    """
    edges = []
    for i, s in enumerate(stats):
        total = s.total_wins + s.total_losses
        if total < min_trades:
            edges.append(None)   # insufficient data — keep current
        else:
            edges.append(s.edge_score)

    valid = [e for e in edges if e is not None]
    if not valid:
        return list(CURRENT_WEIGHTS)

    min_e = min(valid)
    max_e = max(valid)
    e_range = max_e - min_e if max_e != min_e else 1.0

    new_weights = []
    for i, edge in enumerate(edges):
        if edge is None:
            new_weights.append(CURRENT_WEIGHTS[i])
        else:
            # Normalise to [min_weight, max_weight]
            norm = (edge - min_e) / e_range
            w    = min_weight + norm * (max_weight - min_weight)
            new_weights.append(round(w, 2))

    return new_weights


# ── Report ────────────────────────────────────────────────────────────────────

def print_report(stats: List[SignalStats], new_weights: List[float]) -> None:
    print(f"\n{'='*70}")
    print("SIGNAL WEIGHT AUTO-TUNING RESULTS")
    print(f"{'='*70}")
    print(f"\n{'Signal':<16} {'EdgeScore':>9} {'WinAlign':>9} {'LossAlign':>10} "
          f"{'OldWeight':>10} {'NewWeight':>10} {'Change':>8}")
    print("-" * 70)

    for i, (s, nw) in enumerate(zip(stats, new_weights)):
        ow     = CURRENT_WEIGHTS[i] if i < len(CURRENT_WEIGHTS) else 1.0
        change = nw - ow
        total  = s.total_wins + s.total_losses
        flag   = "⚠ (low n)" if total < 10 else ""
        wp     = f"{s.win_rate_when_aligned*100:.0f}%" if total >= 10 else "—"
        lp     = (f"{s.aligned_loss/s.total_losses*100:.0f}%"
                  if s.total_losses > 0 else "—")
        print(f"{s.name:<16} {s.edge_score:>+9.4f} {wp:>9} {lp:>10} "
              f"{ow:>10.2f} {nw:>10.2f} {change:>+8.2f}  {flag}")

    print(f"\n{'='*70}")
    print("NEW WEIGHTS — paste into signals/conviction.py:")
    print(f"{'='*70}")
    fmt = ", ".join(str(w) for w in new_weights)
    print(f"\nWEIGHTS: List[float] = [{fmt}]")
    print(f"MAX_WEIGHTED = sum(WEIGHTS)  # {sum(new_weights):.1f}")
    print()


# ── Apply weights ─────────────────────────────────────────────────────────────

def apply_weights(new_weights: List[float]) -> bool:
    """Write new weights directly into signals/conviction.py."""
    import re
    path = Path(__file__).parent.parent / "signals" / "conviction.py"
    content = path.read_text()
    fmt  = ", ".join(str(w) for w in new_weights)
    new_line = f"WEIGHTS: List[float] = [{fmt}]"
    fixed = re.sub(r"WEIGHTS: List\[float\] = \[.*?\]", new_line, content)
    if fixed == content:
        print("ERROR: Could not find WEIGHTS line in conviction.py")
        return False
    path.write_text(fixed)
    print(f"✓ Weights updated in {path}")
    return True


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)

    parser = argparse.ArgumentParser(
        description="Auto-tune signal weights from backtest CSV output",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m backtest.weight_tuner output/backtest_20260611.csv
  python -m backtest.weight_tuner output/backtest_*.csv --apply
  python -m backtest.weight_tuner output/backtest_*.csv --min-trades 5
        """,
    )
    parser.add_argument("csvfiles", nargs="+", help="Backtest CSV file(s) to analyse")
    parser.add_argument("--apply",      action="store_true", help="Write weights to conviction.py")
    parser.add_argument("--min-trades", type=int, default=10, help="Min trades per signal to trust")
    parser.add_argument("--min-weight", type=float, default=0.3)
    parser.add_argument("--max-weight", type=float, default=2.5)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    # Load all trades from all CSV files
    all_trades: List[TradeEntry] = []
    for path_str in args.csvfiles:
        for csv_path in sorted(Path(".").glob(path_str)) or [Path(path_str)]:
            if csv_path.exists():
                all_trades.extend(load_trades_from_csv(csv_path))

    if not all_trades:
        print("No trades found. Check CSV file paths.")
        sys.exit(1)

    wins   = sum(1 for t in all_trades if t.is_win)
    losses = sum(1 for t in all_trades if not t.is_win)
    print(f"\nLoaded {len(all_trades)} trades ({wins} wins, {losses} losses)")
    print(f"Tickers: {len(set(t.ticker for t in all_trades))}")
    print(f"\nRe-running signals on entry bars (this fetches bar data)…\n")

    stats       = compute_signal_stats(all_trades, verbose=args.verbose)
    new_weights = calc_new_weights(stats, min_trades=args.min_trades,
                                   min_weight=args.min_weight, max_weight=args.max_weight)
    print_report(stats, new_weights)

    if args.apply:
        apply_weights(new_weights)
    else:
        print("Tip: re-run with --apply to write weights directly to conviction.py")
