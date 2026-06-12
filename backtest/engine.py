"""
backtest/engine.py — ENH-01: Historical signal backtesting engine.

Replays historical OHLCV bars through the 7-signal conviction model to
measure whether the strategy has genuine edge — before risking paper money.

How it works:
  1. Load 1-year of daily bars for each ticker (Yahoo Finance)
  2. Pre-compute all signals once per bar into a cache (Step 2 fix)
  3. Walk forward bar-by-bar using the cache — no redundant recomputation
  4. When conviction ≥ threshold and score ≥ min_score → simulate entry
  5. Position exits at: stop loss, take profit, signal flip, or max hold
  6. Track P&L, R-multiple, win rate, expectancy per ticker and overall

Performance fixes vs original:
  - Signal cache: each bar's signals computed once, reused for both entry
    detection and in-position flip checks. Was O(n²) with signal_flip_exit
    on; now O(n) regardless of how long a position is held.
  - Gap-open stop: if the next bar opens through the stop level (overnight
    gap), fill at the open price instead of the stop (conservative).
  - Slippage: 0.1% applied to all entries (configurable). Prevents
    artificially optimistic fills on daily bar opens.

No lookahead bias: signals at bar[t] only see bars[0..t]. Entry fills at
the open of bar[t+1] (next bar open, realistic execution assumption).

Usage:
    python -m backtest.engine --tickers AAPL MSFT NVDA
    python -m backtest.engine --universe nasdaq100 --max 20 -v
    python -m backtest.engine --tickers AAPL --min-score 3 --conviction 60
    python -m backtest.engine --universe sp500 --max 50 --save-csv
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Bootstrap path so imports work when run as __main__ ───────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from data.yahoo_client import Bar, _yfinance_bars
from signals import run_all
from signals.base import TickerAnalysis
from signals.conviction import score_conviction, ConvictionScore
from signals.fibonacci import compute_fibonacci

log = logging.getLogger(__name__)

# ── Minimum bars needed to run all 10 signals reliably ────────────────────────
MIN_BARS_REQUIRED = 30


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class BacktestTrade:
    ticker:            str
    side:              str     # "long" | "short"
    entry_bar:         int     # index in bars list
    exit_bar:          int
    entry_price:       float   # actual fill price (after slippage)
    exit_price:        float
    stop_loss:         float
    take_profit:       float
    qty:               int
    pnl_usd:           float
    pnl_pct:           float
    r_multiple:        float
    exit_reason:       str     # "stop"|"gap_stop"|"take_profit"|"signal_flip"|"max_hold"
    entry_score:       int
    entry_conviction:  float
    entry_date:        str
    exit_date:         str
    slippage_usd:      float = 0.0   # cost of slippage on entry

    @property
    def is_win(self) -> bool:
        return self.pnl_usd > 0

    @property
    def hold_bars(self) -> int:
        return self.exit_bar - self.entry_bar


@dataclass
class BacktestResult:
    ticker:        str
    total_trades:  int
    wins:          int
    losses:        int
    win_rate:      float
    avg_r:         float
    total_pnl_usd: float
    avg_pnl_pct:   float
    expectancy:    float
    max_drawdown:  float
    avg_hold_bars: float
    total_slippage:float
    trades:        List[BacktestTrade] = field(default_factory=list)
    bars_tested:   int = 0
    compute_secs:  float = 0.0   # time to run this ticker's backtest

    @property
    def profit_factor(self) -> float:
        gross_wins   = sum(t.pnl_usd for t in self.trades if t.is_win)
        gross_losses = abs(sum(t.pnl_usd for t in self.trades if not t.is_win))
        return round(gross_wins / gross_losses, 2) if gross_losses else float("inf")

    @property
    def exit_breakdown(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for t in self.trades:
            counts[t.exit_reason] = counts.get(t.exit_reason, 0) + 1
        return counts


@dataclass
class BacktestConfig:
    min_score:          int   = 4      # minimum |net signal score| to enter
    min_conviction:     float = 60.0   # minimum conviction % to enter
    stop_loss_pct:      float = 2.0    # stop loss % from entry (fallback)
    take_profit_pct:    float = 4.0    # take profit % from entry (fallback)
    position_size_usd:  float = 1000.0 # fixed dollar size per trade
    direction:          str   = "both" # "long" | "short" | "both"
    use_fib_levels:     bool  = True   # use Fibonacci stop/TP when available
    signal_flip_exit:   bool  = True   # exit when score flips direction
    max_hold_bars:      int   = 20     # force-exit after N bars
    lookback_bars:      int   = 252    # history bars to fetch (1y daily ≈ 252)
    window:             int   = 60     # rolling signal window size
    slippage_pct:       float = 0.10   # entry slippage % (0.10 = 10 basis points)
    gap_stop_fill:      bool  = True   # fill gap-open stops at open, not stop price


# ── Bar fetching ──────────────────────────────────────────────────────────────

def _fetch_bars(ticker: str) -> List[Bar]:
    """Fetch 1-year of daily bars from Yahoo Finance."""
    bars = _yfinance_bars(ticker, market_open=False)
    log.debug("%s: %d bars loaded", ticker, len(bars))
    return bars


# ── Signal computation + cache ────────────────────────────────────────────────

def _build_signal_cache(
    bars:   List[Bar],
    window: int,
) -> Dict[int, Optional[Tuple[TickerAnalysis, ConvictionScore]]]:
    """
    Pre-compute signals for every bar index in one pass.

    This is the Step 2 fix. Previously, _run_signals_at was called:
      - Once per bar while NOT in a position (entry check)
      - Once per bar while IN a position (signal flip check)
    That's up to 2× N calls per ticker, making signal_flip_exit O(n²).

    By computing once and caching, both lookups hit the dict in O(1).
    For 252 bars and 100 tickers this goes from ~50,400 signal runs to
    ~25,200 — a 50% reduction in compute, regardless of hold length.

    Keys are bar indices. Values are (TickerAnalysis, ConvictionScore) or
    None if there aren't enough bars in the window yet.
    """
    cache: Dict[int, Optional[Tuple[TickerAnalysis, ConvictionScore]]] = {}

    for i in range(len(bars)):
        start       = max(0, i - window + 1)
        window_bars = bars[start: i + 1]

        if len(window_bars) < MIN_BARS_REQUIRED:
            cache[i] = None
            continue

        cur  = window_bars[-1]
        sigs = run_all(window_bars)
        ta   = TickerAnalysis(
            ticker       = "BT",
            price        = cur.close,
            chg_pct      = (cur.close - cur.open) / cur.open * 100 if cur.open else 0,
            volume       = cur.volume,
            bars         = len(window_bars),
            mode         = "Daily",
            company_name = "",
            signals      = sigs,
        )
        ta.fib = compute_fibonacci(
            ticker        = "BT",
            bars          = window_bars,
            current_price = cur.close,
            net_score     = ta.net_score,
        )
        cache[i] = (ta, score_conviction(ta))

    return cache


# ── Position sizing ───────────────────────────────────────────────────────────

def _calc_qty(entry_price: float, cfg: BacktestConfig) -> int:
    if entry_price <= 0:
        return 0
    return max(1, int(cfg.position_size_usd // entry_price))


def _calc_levels(
    entry:     float,
    direction: str,
    cfg:       BacktestConfig,
    fib:       Optional[object],
) -> Tuple[float, float]:
    """Return (stop_loss, take_profit) — Fibonacci preferred, % fallback."""
    if cfg.use_fib_levels and fib:
        sl = getattr(fib, "stop_loss", None)
        tp = getattr(fib, "target_1",  None)
        if sl and tp:
            return sl, tp

    if direction == "long":
        sl = round(entry * (1 - cfg.stop_loss_pct   / 100), 2)
        tp = round(entry * (1 + cfg.take_profit_pct / 100), 2)
    else:
        sl = round(entry * (1 + cfg.stop_loss_pct   / 100), 2)
        tp = round(entry * (1 - cfg.take_profit_pct / 100), 2)
    return sl, tp


def _apply_slippage(raw_price: float, direction: str, cfg: BacktestConfig) -> float:
    """Apply entry slippage. Longs fill slightly higher, shorts slightly lower."""
    factor = 1 + cfg.slippage_pct / 100 if direction == "long" else 1 - cfg.slippage_pct / 100
    return round(raw_price * factor, 4)


# ── Core walk-forward loop ────────────────────────────────────────────────────

def _backtest_ticker(
    ticker: str,
    bars:   List[Bar],
    cfg:    BacktestConfig,
) -> BacktestResult:
    """
    Walk forward through bars using a pre-built signal cache.
    All signal data is read from the cache — zero recomputation.
    """
    t_start = time.perf_counter()

    # ── Pre-compute all signals once ─────────────────────────────────────────
    cache = _build_signal_cache(bars, cfg.window)

    trades:      List[BacktestTrade] = []
    in_position: bool  = False
    trade_dir:   str   = ""
    entry_price: float = 0.0
    stop_loss:   float = 0.0
    take_profit: float = 0.0
    entry_bar_i: int   = 0
    entry_score: int   = 0
    entry_conv:  float = 0.0
    qty:         int   = 0
    entry_slip:  float = 0.0

    equity       = cfg.position_size_usd
    peak_equity  = cfg.position_size_usd
    max_drawdown = 0.0

    for i in range(MIN_BARS_REQUIRED, len(bars) - 1):
        bar_now  = bars[i]
        bar_next = bars[i + 1]

        if in_position:
            # ── Exit checks ───────────────────────────────────────────────────
            exit_reason: Optional[str] = None
            exit_price = bar_now.close

            if trade_dir == "long":
                # Gap-open through stop (conservative fill at open, not stop)
                if cfg.gap_stop_fill and bar_now.open <= stop_loss:
                    exit_reason = "gap_stop"
                    exit_price  = bar_now.open
                elif bar_now.low <= stop_loss:
                    exit_reason = "stop"
                    exit_price  = stop_loss
                elif bar_now.high >= take_profit:
                    exit_reason = "take_profit"
                    exit_price  = take_profit
            else:  # short
                if cfg.gap_stop_fill and bar_now.open >= stop_loss:
                    exit_reason = "gap_stop"
                    exit_price  = bar_now.open
                elif bar_now.high >= stop_loss:
                    exit_reason = "stop"
                    exit_price  = stop_loss
                elif bar_now.low <= take_profit:
                    exit_reason = "take_profit"
                    exit_price  = take_profit

            # Signal flip exit — read from cache (no recomputation)
            if not exit_reason and cfg.signal_flip_exit:
                cached = cache.get(i)
                if cached:
                    ta_now, _ = cached
                    if trade_dir == "long"  and ta_now.net_score < 0:
                        exit_reason = "signal_flip"
                        exit_price  = bar_now.close
                    elif trade_dir == "short" and ta_now.net_score > 0:
                        exit_reason = "signal_flip"
                        exit_price  = bar_now.close

            # Max hold exit
            if not exit_reason and (i - entry_bar_i) >= cfg.max_hold_bars:
                exit_reason = "max_hold"
                exit_price  = bar_now.close

            if exit_reason:
                if trade_dir == "long":
                    pnl_usd = (exit_price - entry_price) * qty
                    pnl_pct = (exit_price - entry_price) / entry_price * 100
                else:
                    pnl_usd = (entry_price - exit_price) * qty
                    pnl_pct = (entry_price - exit_price) / entry_price * 100

                risk   = abs(entry_price - stop_loss)
                r_mult = round(pnl_usd / (risk * qty), 2) if risk and qty else 0.0

                equity      += pnl_usd
                peak_equity  = max(peak_equity, equity)
                drawdown     = (peak_equity - equity) / peak_equity * 100
                max_drawdown = max(max_drawdown, drawdown)

                trades.append(BacktestTrade(
                    ticker            = ticker,
                    side              = trade_dir,
                    entry_bar         = entry_bar_i,
                    exit_bar          = i,
                    entry_price       = entry_price,
                    exit_price        = round(exit_price, 2),
                    stop_loss         = stop_loss,
                    take_profit       = take_profit,
                    qty               = qty,
                    pnl_usd           = round(pnl_usd, 2),
                    pnl_pct           = round(pnl_pct, 2),
                    r_multiple        = r_mult,
                    exit_reason       = exit_reason,
                    entry_score       = entry_score,
                    entry_conviction  = entry_conv,
                    entry_date        = bars[entry_bar_i].timestamp.strftime("%Y-%m-%d"),
                    exit_date         = bar_now.timestamp.strftime("%Y-%m-%d"),
                    slippage_usd      = entry_slip,
                ))
                in_position = False

        else:
            # ── Entry check — read from cache ─────────────────────────────────
            cached = cache.get(i)
            if not cached:
                continue
            ta_now, cs_now = cached

            abs_score = abs(ta_now.net_score)
            if abs_score < cfg.min_score or cs_now.conviction_pct < cfg.min_conviction:
                continue

            direction = ""
            if ta_now.net_score > 0 and cfg.direction in ("long", "both"):
                direction = "long"
            elif ta_now.net_score < 0 and cfg.direction in ("short", "both"):
                direction = "short"

            if not direction:
                continue

            # Fill at next bar open + slippage
            raw_fill   = bar_next.open
            entry_fill = _apply_slippage(raw_fill, direction, cfg)
            qty_calc   = _calc_qty(entry_fill, cfg)
            if qty_calc == 0:
                continue

            sl, tp = _calc_levels(entry_fill, direction, cfg, ta_now.fib)

            in_position  = True
            trade_dir    = direction
            entry_price  = entry_fill
            stop_loss    = sl
            take_profit  = tp
            entry_bar_i  = i + 1
            entry_score  = ta_now.net_score
            entry_conv   = cs_now.conviction_pct
            qty          = qty_calc
            entry_slip   = round(abs(entry_fill - raw_fill) * qty_calc, 2)

    # ── Compile result ────────────────────────────────────────────────────────
    n        = len(trades)
    wins     = [t for t in trades if t.is_win]
    losses   = [t for t in trades if not t.is_win]

    win_rate    = len(wins) / n * 100        if n      else 0.0
    avg_r       = sum(t.r_multiple for t in trades) / n if n else 0.0
    total_pnl   = sum(t.pnl_usd for t in trades)
    avg_pnl_pct = sum(t.pnl_pct for t in trades) / n   if n      else 0.0
    avg_hold    = sum(t.hold_bars for t in trades) / n  if n      else 0.0
    total_slip  = sum(t.slippage_usd for t in trades)

    avg_win   = sum(t.pnl_usd for t in wins)   / len(wins)   if wins   else 0.0
    avg_loss  = sum(t.pnl_usd for t in losses) / len(losses) if losses else 0.0
    expectancy = (avg_win * win_rate / 100) + (avg_loss * (1 - win_rate / 100))

    return BacktestResult(
        ticker         = ticker,
        total_trades   = n,
        wins           = len(wins),
        losses         = len(losses),
        win_rate       = round(win_rate, 1),
        avg_r          = round(avg_r, 2),
        total_pnl_usd  = round(total_pnl, 2),
        avg_pnl_pct    = round(avg_pnl_pct, 2),
        expectancy     = round(expectancy, 2),
        max_drawdown   = round(max_drawdown, 1),
        avg_hold_bars  = round(avg_hold, 1),
        total_slippage = round(total_slip, 2),
        trades         = trades,
        bars_tested    = len(bars),
        compute_secs   = round(time.perf_counter() - t_start, 2),
    )


# ── Multi-ticker runner ───────────────────────────────────────────────────────

def run_backtest(
    tickers: List[str],
    cfg:     BacktestConfig = None,
    verbose: bool = False,
) -> Tuple[List[BacktestResult], Dict]:
    """
    Run backtest for all tickers. Returns (results_sorted_by_expectancy, agg).
    """
    cfg = cfg or BacktestConfig()
    results: List[BacktestResult] = []

    print(f"\n{'='*65}")
    print(f"BACKTEST  —  {len(tickers)} ticker(s)")
    print(f"  min_score={cfg.min_score}  conviction={cfg.min_conviction}%  "
          f"direction={cfg.direction}")
    print(f"  stop={cfg.stop_loss_pct}%  tp={cfg.take_profit_pct}%  "
          f"size=${cfg.position_size_usd:.0f}  slippage={cfg.slippage_pct:.2f}%")
    print(f"  signal_flip_exit={cfg.signal_flip_exit}  "
          f"gap_stop_fill={cfg.gap_stop_fill}  "
          f"max_hold={cfg.max_hold_bars}b")
    print(f"{'='*65}")

    t0 = time.perf_counter()
    for i, ticker in enumerate(tickers, 1):
        print(f"[{i:3d}/{len(tickers)}] {ticker:7s}", end="", flush=True)

        bars = _fetch_bars(ticker)
        if len(bars) < MIN_BARS_REQUIRED + 5:
            print(f"  — insufficient data ({len(bars)} bars)")
            continue

        r = _backtest_ticker(ticker, bars, cfg)
        results.append(r)

        if verbose:
            breakdown = "  ".join(f"{k}:{v}" for k, v in sorted(r.exit_breakdown.items()))
            print(
                f"  {r.total_trades:3d}T  WR:{r.win_rate:.0f}%  "
                f"R:{r.avg_r:+.2f}  E:{r.expectancy:+.2f}  "
                f"P&L:${r.total_pnl_usd:+,.0f}  DD:{r.max_drawdown:.1f}%  "
                f"slip:${r.total_slippage:.0f}  [{breakdown}]  {r.compute_secs:.1f}s"
            )
        else:
            flag = "✓" if r.expectancy > 0 else "✗"
            print(
                f"  {flag}  {r.total_trades:3d}T  "
                f"WR:{r.win_rate:.0f}%  R:{r.avg_r:+.2f}  E:{r.expectancy:+.2f}"
            )

    elapsed = round(time.perf_counter() - t0, 1)
    results.sort(key=lambda r: r.expectancy, reverse=True)

    # ── Aggregate ─────────────────────────────────────────────────────────────
    all_trades = [t for r in results for t in r.trades]
    n          = len(all_trades)
    wins       = [t for t in all_trades if t.is_win]
    losses     = [t for t in all_trades if not t.is_win]

    avg_win  = sum(t.pnl_usd for t in wins)   / len(wins)   if wins   else 0.0
    avg_loss = sum(t.pnl_usd for t in losses) / len(losses) if losses else 0.0
    wr_agg   = len(wins) / n * 100 if n else 0.0

    exit_counts: Dict[str, int] = {}
    for t in all_trades:
        exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1

    agg = {
        "tickers_tested":     len(results),
        "profitable_tickers": sum(1 for r in results if r.total_pnl_usd > 0),
        "total_trades":       n,
        "win_rate":           round(wr_agg, 1),
        "avg_r":              round(sum(t.r_multiple for t in all_trades) / n, 2) if n else 0,
        "total_pnl_usd":      round(sum(t.pnl_usd for t in all_trades), 2),
        "avg_win_usd":        round(avg_win, 2),
        "avg_loss_usd":       round(avg_loss, 2),
        "total_slippage_usd": round(sum(t.slippage_usd for t in all_trades), 2),
        "expectancy":         round((avg_win * wr_agg / 100) + (avg_loss * (1 - wr_agg / 100)), 2) if n else 0,
        "exit_breakdown":     exit_counts,
        "elapsed_secs":       elapsed,
    }
    return results, agg


# ── Report printer ────────────────────────────────────────────────────────────

def print_report(results: List[BacktestResult], agg: Dict) -> None:
    print(f"\n{'='*65}")
    print("RESULTS")
    print(f"{'='*65}")

    hdr = (f"{'':1s}{'Ticker':7s}  {'T':>4}  {'WR':>5}  {'AvgR':>5}  "
           f"{'E':>6}  {'P&L':>9}  {'DD':>5}  {'Hold':>4}  {'PF':>4}")
    print(hdr)
    print("-" * len(hdr))

    for r in results:
        flag = "+" if r.expectancy > 0 else " "
        print(
            f"{flag}{r.ticker:7s}  {r.total_trades:>4d}  {r.win_rate:>4.0f}%  "
            f"{r.avg_r:>+5.2f}  {r.expectancy:>+6.2f}  "
            f"${r.total_pnl_usd:>+8,.0f}  {r.max_drawdown:>4.1f}%  "
            f"{r.avg_hold_bars:>4.0f}b  {r.profit_factor:>4.1f}x"
        )

    print(f"\n{'='*65}")
    print("AGGREGATE")
    print(f"  Tickers tested:     {agg['tickers_tested']}")
    print(f"  Profitable:         {agg['profitable_tickers']} / {agg['tickers_tested']}")
    print(f"  Total trades:       {agg['total_trades']}")
    print(f"  Win rate:           {agg['win_rate']:.1f}%")
    print(f"  Average R:          {agg['avg_r']:+.2f}")
    print(f"  Expectancy:         ${agg['expectancy']:+.2f} per trade")
    print(f"  Total P&L:          ${agg['total_pnl_usd']:+,.2f}")
    print(f"  Avg win:            ${agg['avg_win_usd']:+.2f}")
    print(f"  Avg loss:           ${agg['avg_loss_usd']:+.2f}")
    print(f"  Total slippage:     ${agg['total_slippage_usd']:.2f}")

    bd = agg.get("exit_breakdown", {})
    if bd:
        parts = "  ".join(f"{k}:{v}" for k, v in sorted(bd.items()))
        print(f"  Exit breakdown:     {parts}")

    print(f"  Elapsed:            {agg['elapsed_secs']:.1f}s")

    # Breakeven WR = loss_size / (win_size + loss_size) — correct for any R/R ratio
    avg_win_abs  = abs(agg.get("avg_win_usd", 1) or 1)
    avg_loss_abs = abs(agg.get("avg_loss_usd", 1) or 1)
    breakeven_wr = avg_loss_abs / (avg_win_abs + avg_loss_abs) * 100
    margin       = agg.get("win_rate", 0) - breakeven_wr
    has_edge     = agg.get("expectancy", 0) > 0 and margin > 0
    verdict = (f"✓ EDGE DETECTED  (WR {agg.get('win_rate',0):.1f}% > breakeven {breakeven_wr:.1f}%, "
               f"margin={margin:+.1f}%)" if has_edge else
               f"✗ NO EDGE  (WR {agg.get('win_rate',0):.1f}% vs breakeven {breakeven_wr:.1f}%"
               f", margin={margin:+.1f}%)")
    print(f"\n  {'─'*45}")
    print(f"  Verdict: {verdict}")
    print(f"  {'─'*45}\n")


# ── CSV export ────────────────────────────────────────────────────────────────

def save_results_csv(
    results: List[BacktestResult],
    agg:     Dict,
    cfg:     BacktestConfig,
    path:    Optional[Path] = None,
) -> Path:
    """
    Save per-ticker results AND every individual trade to a timestamped CSV.
    Two sections in one file: summary rows first, then all trade rows.
    """
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = path or (config.OUTPUT_DIR / f"backtest_{ts}.csv")
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="") as f:
        w = csv.writer(f)

        # ── Config block ──────────────────────────────────────────────────────
        w.writerow(["# BACKTEST CONFIG"])
        w.writerow(["min_score", "conviction", "stop_pct", "tp_pct",
                    "direction", "size_usd", "slippage_pct",
                    "signal_flip", "gap_stop", "max_hold"])
        w.writerow([cfg.min_score, cfg.min_conviction, cfg.stop_loss_pct,
                    cfg.take_profit_pct, cfg.direction, cfg.position_size_usd,
                    cfg.slippage_pct, cfg.signal_flip_exit,
                    cfg.gap_stop_fill, cfg.max_hold_bars])
        w.writerow([])

        # ── Per-ticker summary ────────────────────────────────────────────────
        w.writerow(["# PER-TICKER SUMMARY"])
        w.writerow(["ticker", "trades", "wins", "losses", "win_rate_pct",
                    "avg_r", "expectancy", "total_pnl_usd", "avg_pnl_pct",
                    "max_drawdown_pct", "avg_hold_bars", "profit_factor",
                    "total_slippage_usd", "bars_tested", "compute_secs",
                    "exit_stop", "exit_gap_stop", "exit_take_profit",
                    "exit_signal_flip", "exit_max_hold"])
        for r in results:
            bd = r.exit_breakdown
            w.writerow([
                r.ticker, r.total_trades, r.wins, r.losses,
                r.win_rate, r.avg_r, r.expectancy, r.total_pnl_usd,
                r.avg_pnl_pct, r.max_drawdown, r.avg_hold_bars,
                r.profit_factor, r.total_slippage, r.bars_tested,
                r.compute_secs,
                bd.get("stop", 0), bd.get("gap_stop", 0),
                bd.get("take_profit", 0), bd.get("signal_flip", 0),
                bd.get("max_hold", 0),
            ])

        # ── Aggregate row ─────────────────────────────────────────────────────
        w.writerow([])
        w.writerow(["# AGGREGATE"])
        w.writerow(["tickers_tested", "profitable", "total_trades", "win_rate",
                    "avg_r", "expectancy", "total_pnl", "avg_win", "avg_loss",
                    "total_slippage", "elapsed_secs"])
        w.writerow([
            agg["tickers_tested"], agg["profitable_tickers"],
            agg["total_trades"],   agg["win_rate"], agg["avg_r"],
            agg["expectancy"],     agg["total_pnl_usd"],
            agg["avg_win_usd"],    agg["avg_loss_usd"],
            agg["total_slippage_usd"], agg["elapsed_secs"],
        ])

        # ── Individual trades ─────────────────────────────────────────────────
        w.writerow([])
        w.writerow(["# ALL TRADES"])
        w.writerow(["ticker", "side", "entry_date", "exit_date", "hold_bars",
                    "entry_price", "exit_price", "stop_loss", "take_profit",
                    "qty", "pnl_usd", "pnl_pct", "r_multiple", "exit_reason",
                    "entry_score", "conviction_pct", "slippage_usd"])
        for r in results:
            for t in sorted(r.trades, key=lambda x: x.entry_date):
                w.writerow([
                    t.ticker, t.side, t.entry_date, t.exit_date, t.hold_bars,
                    t.entry_price, t.exit_price, t.stop_loss, t.take_profit,
                    t.qty, t.pnl_usd, t.pnl_pct, t.r_multiple, t.exit_reason,
                    t.entry_score, t.entry_conviction, t.slippage_usd,
                ])

    print(f"  Results saved → {path}")
    return path


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Backtest the 7-signal conviction model on historical daily bars",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m backtest.engine --tickers AAPL MSFT NVDA -v
  python -m backtest.engine --universe nasdaq100 --max 20 --save-csv
  python -m backtest.engine --tickers TSLA --min-score 3 --conviction 55
  python -m backtest.engine --tickers AAPL --stop 1.5 --tp 4.5 --no-fib -v
        """,
    )
    parser.add_argument("--tickers",     nargs="+",    help="Specific tickers to backtest")
    parser.add_argument("--universe",    default="nasdaq100", help="Universe name (nasdaq100, sp500, …)")
    parser.add_argument("--max",         type=int,  default=20,   help="Max tickers from universe (0=all)")
    parser.add_argument("--min-score",   type=int,  default=4,    help="Min |net signal score| to enter (1–7)")
    parser.add_argument("--conviction",  type=float,default=60.0, help="Min conviction %% to enter")
    parser.add_argument("--stop",        type=float,default=2.0,  help="Stop loss %% from entry")
    parser.add_argument("--tp",          type=float,default=4.0,  help="Take profit %% from entry")
    parser.add_argument("--direction",   default="both", choices=["long", "short", "both"])
    parser.add_argument("--size",        type=float,default=1000.0, help="Position size in USD")
    parser.add_argument("--slippage",    type=float,default=0.10,  help="Entry slippage %% (default 0.10)")
    parser.add_argument("--no-fib",      action="store_true", help="Disable Fibonacci levels; use %% stop/TP")
    parser.add_argument("--no-flip",     action="store_true", help="Disable signal-flip exit")
    parser.add_argument("--no-gap-stop", action="store_true", help="Disable gap-open stop fill (fill at stop price)")
    parser.add_argument("--max-hold",    type=int,  default=20,   help="Force exit after N bars (default 20)")
    parser.add_argument("--save-csv",    action="store_true", help="Save results to output/backtest_*.csv")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print per-ticker exit breakdown and timing")
    args = parser.parse_args()

    # ── Resolve ticker list ───────────────────────────────────────────────────
    if args.tickers:
        tickers = [t.upper().strip() for t in args.tickers]
    else:
        from universes import get_tickers
        tickers = get_tickers(args.universe, 0)
        if args.max:
            tickers = tickers[:args.max]

    if not tickers:
        print("No tickers found. Check --tickers or --universe argument.")
        sys.exit(1)

    # ── Build config ──────────────────────────────────────────────────────────
    cfg = BacktestConfig(
        min_score         = args.min_score,
        min_conviction    = args.conviction,
        stop_loss_pct     = args.stop,
        take_profit_pct   = args.tp,
        direction         = args.direction,
        position_size_usd = args.size,
        slippage_pct      = args.slippage,
        use_fib_levels    = not args.no_fib,
        signal_flip_exit  = not args.no_flip,
        gap_stop_fill     = not args.no_gap_stop,
        max_hold_bars     = args.max_hold,
    )

    # ── Run ───────────────────────────────────────────────────────────────────
    results, agg = run_backtest(tickers, cfg, verbose=args.verbose)
    print_report(results, agg)

    if args.save_csv:
        save_results_csv(results, agg, cfg)
