"""
trading/pnl_tracker.py — ENH-05: Trade P&L tracking and performance metrics.

Records every trade (open + close) to a JSON ledger in output/trade_ledger.json.
Computes session and cumulative performance statistics printed to terminal
and included in the email report.

Metrics tracked:
  - Win rate (% of closed trades profitable)
  - Average R (average return as multiple of risk taken)
  - Average P&L per trade ($ and %)
  - Best / worst trade
  - Total trades, total P&L
  - Streak (current consecutive wins or losses)
  - Expectancy (avg win × win rate − avg loss × loss rate)

Usage:
  # Called by trade_engine after every closed position:
  from trading.pnl_tracker import record_trade, get_performance_summary
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import config

log = logging.getLogger(__name__)

LEDGER_PATH = config.OUTPUT_DIR / "trade_ledger.json"


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class TradeRecord:
    trade_id:     str
    ticker:       str
    company_name: str
    side:         str           # "long" | "short"
    entry_price:  float
    exit_price:   float
    qty:          int
    pnl_usd:      float
    pnl_pct:      float
    r_multiple:   float         # P&L / initial risk (stop distance)
    entry_stop:   float         # stop at entry
    entry_tp:     float         # take-profit at entry
    exit_reason:  str           # "stop" | "take_profit" | "manual" | "signal_flip"
    opened_at:    str
    closed_at:    str
    conviction:   float = 0.0
    score:        int   = 0
    session:      str   = ""    # "premarket" | "open" | "afterhours"

    @property
    def is_win(self) -> bool:
        return self.pnl_usd > 0

    @property
    def duration_mins(self) -> Optional[float]:
        try:
            t0 = datetime.fromisoformat(self.opened_at)
            t1 = datetime.fromisoformat(self.closed_at)
            return round((t1 - t0).total_seconds() / 60, 1)
        except Exception:
            return None


@dataclass
class PerformanceSummary:
    total_trades:     int
    wins:             int
    losses:           int
    win_rate:         float       # 0–100 %
    avg_win_usd:      float
    avg_loss_usd:     float
    avg_pnl_usd:      float
    avg_pnl_pct:      float
    avg_r:            float       # average R-multiple
    total_pnl_usd:    float
    best_trade:       Optional[TradeRecord]
    worst_trade:      Optional[TradeRecord]
    expectancy:       float       # avg_win × win_rate − avg_loss × loss_rate
    current_streak:   int         # + = win streak, − = loss streak
    streak_type:      str         # "W" | "L" | ""
    session_trades:   int         # trades executed this scan session
    session_pnl:      float


# ── Ledger I/O ────────────────────────────────────────────────────────────────

def _load_ledger() -> List[TradeRecord]:
    if not LEDGER_PATH.exists():
        return []
    try:
        raw = json.loads(LEDGER_PATH.read_text())
        return [TradeRecord(**r) for r in raw]
    except Exception as e:
        log.warning("trade_ledger load failed: %s", e)
        return []


def _save_ledger(trades: List[TradeRecord]) -> None:
    try:
        LEDGER_PATH.write_text(
            json.dumps([asdict(t) for t in trades], indent=2)
        )
    except Exception as e:
        log.warning("trade_ledger save failed: %s", e)


# ── Record a closed trade ─────────────────────────────────────────────────────

def record_trade(
    ticker:       str,
    company_name: str,
    side:         str,
    entry_price:  float,
    exit_price:   float,
    qty:          int,
    entry_stop:   float,
    entry_tp:     float,
    exit_reason:  str,
    opened_at:    str,
    conviction:   float = 0.0,
    score:        int = 0,
    session:      str = "",
) -> TradeRecord:
    """
    Record a completed trade to the ledger and return the TradeRecord.
    Called automatically by position_monitor when a position is closed.
    """
    if side == "long":
        pnl_usd = (exit_price - entry_price) * qty
        pnl_pct = (exit_price - entry_price) / entry_price * 100
        risk    = abs(entry_price - entry_stop) if entry_stop else entry_price * 0.02
    else:
        pnl_usd = (entry_price - exit_price) * qty
        pnl_pct = (entry_price - exit_price) / entry_price * 100
        risk    = abs(entry_stop - entry_price) if entry_stop else entry_price * 0.02

    r_multiple = round(pnl_usd / (risk * qty), 2) if risk and qty else 0.0

    trade_id = f"{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    record = TradeRecord(
        trade_id    = trade_id,
        ticker      = ticker,
        company_name= company_name,
        side        = side,
        entry_price = round(entry_price, 2),
        exit_price  = round(exit_price, 2),
        qty         = qty,
        pnl_usd     = round(pnl_usd, 2),
        pnl_pct     = round(pnl_pct, 2),
        r_multiple  = r_multiple,
        entry_stop  = round(entry_stop, 2) if entry_stop else 0.0,
        entry_tp    = round(entry_tp, 2) if entry_tp else 0.0,
        exit_reason = exit_reason,
        opened_at   = opened_at,
        closed_at   = datetime.now().isoformat(),
        conviction  = conviction,
        score       = score,
        session     = session,
    )

    trades = _load_ledger()
    trades.append(record)
    _save_ledger(trades)

    log.info(
        "Trade recorded: %s %s entry=$%.2f exit=$%.2f P&L=$%+.2f (%+.2f%%) R=%.2f reason=%s",
        side.upper(), ticker, entry_price, exit_price, pnl_usd, pnl_pct, r_multiple, exit_reason,
    )
    return record


# ── Performance calculation ───────────────────────────────────────────────────

def _current_streak(trades: List[TradeRecord]) -> Tuple[int, str]:
    """Return (streak_count, 'W'|'L'|'') from most recent trades."""
    if not trades:
        return 0, ""
    streak_type = "W" if trades[-1].is_win else "L"
    count = 0
    for t in reversed(trades):
        if (t.is_win and streak_type == "W") or (not t.is_win and streak_type == "L"):
            count += 1
        else:
            break
    return (count if streak_type == "W" else -count), streak_type


def get_performance_summary(session_trade_ids: Optional[List[str]] = None) -> PerformanceSummary:
    """
    Compute performance metrics over all recorded trades.

    Args:
        session_trade_ids: trade_ids from the current scan session
                           (used to compute session P&L separately)
    """
    trades = _load_ledger()
    if not trades:
        return PerformanceSummary(
            total_trades=0, wins=0, losses=0, win_rate=0.0,
            avg_win_usd=0.0, avg_loss_usd=0.0, avg_pnl_usd=0.0,
            avg_pnl_pct=0.0, avg_r=0.0, total_pnl_usd=0.0,
            best_trade=None, worst_trade=None, expectancy=0.0,
            current_streak=0, streak_type="",
            session_trades=0, session_pnl=0.0,
        )

    wins   = [t for t in trades if t.is_win]
    losses = [t for t in trades if not t.is_win]
    n      = len(trades)

    win_rate    = len(wins) / n * 100
    avg_win     = sum(t.pnl_usd for t in wins)   / len(wins)   if wins   else 0.0
    avg_loss    = sum(t.pnl_usd for t in losses) / len(losses) if losses else 0.0
    avg_pnl     = sum(t.pnl_usd for t in trades) / n
    avg_pnl_pct = sum(t.pnl_pct for t in trades) / n
    avg_r       = sum(t.r_multiple for t in trades) / n
    total_pnl   = sum(t.pnl_usd for t in trades)

    # Expectancy = (avg_win × win_rate) + (avg_loss × loss_rate)
    # avg_loss is negative for losing trades; formula naturally handles it
    expectancy  = (avg_win * win_rate / 100) + (avg_loss * (1 - win_rate / 100))

    best  = max(trades, key=lambda t: t.pnl_usd)
    worst = min(trades, key=lambda t: t.pnl_usd)
    streak, streak_type = _current_streak(trades)

    session_ids = set(session_trade_ids or [])
    session_tr  = [t for t in trades if t.trade_id in session_ids]
    session_pnl = sum(t.pnl_usd for t in session_tr)

    return PerformanceSummary(
        total_trades  = n,
        wins          = len(wins),
        losses        = len(losses),
        win_rate      = round(win_rate, 1),
        avg_win_usd   = round(avg_win, 2),
        avg_loss_usd  = round(avg_loss, 2),
        avg_pnl_usd   = round(avg_pnl, 2),
        avg_pnl_pct   = round(avg_pnl_pct, 2),
        avg_r         = round(avg_r, 2),
        total_pnl_usd = round(total_pnl, 2),
        best_trade    = best,
        worst_trade   = worst,
        expectancy    = round(expectancy, 2),
        current_streak= streak,
        streak_type   = streak_type,
        session_trades= len(session_tr),
        session_pnl   = round(session_pnl, 2),
    )


def format_summary_terminal(ps: PerformanceSummary) -> str:
    """Return a Rich-formatted string for terminal display."""
    if ps.total_trades == 0:
        return "[dim]No closed trades yet — P&L data will appear after first position closes.[/]"

    streak_str = ""
    if ps.current_streak != 0:
        col = "green" if ps.streak_type == "W" else "red"
        streak_str = f"  [{col}]{abs(ps.current_streak)}-{ps.streak_type} streak[/]"

    color = "green" if ps.total_pnl_usd >= 0 else "red"
    wr_color = "green" if ps.win_rate >= 50 else "red"

    return (
        f"[bold]Paper Trade Performance[/] ({ps.total_trades} closed trades){streak_str}\n"
        f"  Win rate: [{wr_color}]{ps.win_rate:.1f}%[/]  "
        f"Avg R: [cyan]{ps.avg_r:+.2f}[/]  "
        f"Expectancy: [cyan]${ps.expectancy:+.2f}[/]\n"
        f"  Avg win: [green]${ps.avg_win_usd:+.2f}[/]  "
        f"Avg loss: [red]${ps.avg_loss_usd:+.2f}[/]  "
        f"Total P&L: [{color}]${ps.total_pnl_usd:+,.2f}[/]\n"
        f"  Best: [green]{ps.best_trade.ticker} ${ps.best_trade.pnl_usd:+.2f}[/]  "
        f"Worst: [red]{ps.worst_trade.ticker} ${ps.worst_trade.pnl_usd:+.2f}[/]"
    )


def format_summary_html(ps: PerformanceSummary) -> str:
    """Return an HTML block for the email report."""
    if ps.total_trades == 0:
        return ""

    wr_color = "#1D6F42" if ps.win_rate >= 50 else "#9C0006"
    pnl_color = "#1D6F42" if ps.total_pnl_usd >= 0 else "#9C0006"

    streak_html = ""
    if ps.current_streak != 0:
        sc = "#1D6F42" if ps.streak_type == "W" else "#9C0006"
        streak_html = (f'<span style="color:{sc};font-weight:700;margin-left:12px">'
                       f'{abs(ps.current_streak)}-{ps.streak_type} streak</span>')

    best  = ps.best_trade
    worst = ps.worst_trade

    return f"""
<h2 style="color:#2E75B6;border-bottom:2px solid #C9D8F0;padding-bottom:8px;
           font-size:18px;margin:28px 0 16px">
  📊 Paper Trade Performance — {ps.total_trades} Closed Trades{streak_html}
</h2>
<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px">
  <div style="background:#F0F8FF;border-radius:6px;padding:10px 16px;min-width:130px;text-align:center">
    <div style="font-size:24px;font-weight:700;color:{wr_color}">{ps.win_rate:.1f}%</div>
    <div style="font-size:11px;color:#666">Win Rate</div>
    <div style="font-size:11px;color:#555">{ps.wins}W / {ps.losses}L</div>
  </div>
  <div style="background:#F0F8FF;border-radius:6px;padding:10px 16px;min-width:130px;text-align:center">
    <div style="font-size:24px;font-weight:700;color:#1E6091">{ps.avg_r:+.2f}R</div>
    <div style="font-size:11px;color:#666">Avg R-Multiple</div>
  </div>
  <div style="background:#F0F8FF;border-radius:6px;padding:10px 16px;min-width:130px;text-align:center">
    <div style="font-size:24px;font-weight:700;color:#1E6091">${ps.expectancy:+.2f}</div>
    <div style="font-size:11px;color:#666">Expectancy/Trade</div>
  </div>
  <div style="background:#F0F8FF;border-radius:6px;padding:10px 16px;min-width:130px;text-align:center">
    <div style="font-size:24px;font-weight:700;color:{pnl_color}">${ps.total_pnl_usd:+,.2f}</div>
    <div style="font-size:11px;color:#666">Total P&L</div>
  </div>
  <div style="background:#F0FFF6;border-radius:6px;padding:10px 16px;min-width:130px;text-align:center">
    <div style="font-size:18px;font-weight:700;color:#1D6F42">${ps.avg_win_usd:+.2f}</div>
    <div style="font-size:11px;color:#666">Avg Win</div>
  </div>
  <div style="background:#FFF5F5;border-radius:6px;padding:10px 16px;min-width:130px;text-align:center">
    <div style="font-size:18px;font-weight:700;color:#9C0006">${ps.avg_loss_usd:+.2f}</div>
    <div style="font-size:11px;color:#666">Avg Loss</div>
  </div>
</div>
<table style="font-size:12px;border-collapse:collapse;width:100%">
  <tr style="background:#EEF2F7">
    <td style="padding:5px 10px;color:#666">Best trade:</td>
    <td style="padding:5px 10px;font-weight:700;color:#1D6F42">
      {best.ticker} {best.company_name} — ${best.pnl_usd:+.2f} ({best.pnl_pct:+.2f}%) [{best.exit_reason}]
    </td>
  </tr>
  <tr>
    <td style="padding:5px 10px;color:#666">Worst trade:</td>
    <td style="padding:5px 10px;font-weight:700;color:#9C0006">
      {worst.ticker} {worst.company_name} — ${worst.pnl_usd:+.2f} ({worst.pnl_pct:+.2f}%) [{worst.exit_reason}]
    </td>
  </tr>
</table>
<p style="font-size:11px;color:#999;margin-top:8px">
  Paper trading only. Past performance does not guarantee future results.
</p>"""
