"""
trading/position_monitor.py — ENH-04: Stop-loss & take-profit monitoring.

Bracket orders placed via Alpaca protect positions at entry time only.
Between scans, prices can gap through stop levels before Alpaca's bracket
triggers. This module runs at the START of every scan to:

  1. Fetch all open positions from Alpaca
  2. Compare current price against the stored stop/TP levels
  3. Close positions that have breached stop OR reached take-profit
  4. Log a summary — included in email if any positions were closed

Stop/TP levels are stored in a local JSON file (output/position_log.json)
written when a position is opened. Alpaca bracket orders also protect at
the broker level, so this is a secondary safety layer.

Usage (called automatically at scan start in main.py):
    from trading.position_monitor import run_position_monitor
    monitor_report = run_position_monitor()
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import config
from trading.alpaca_client import AlpacaClient, OrderResult, Position, get_client
from trading.pnl_tracker import record_trade

log = logging.getLogger(__name__)

POSITION_LOG = config.OUTPUT_DIR / "position_log.json"


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class PositionRecord:
    """Stored metadata for an open position."""
    ticker:       str
    side:         str           # "long" | "short"
    entry_price:  float
    stop_loss:    float
    take_profit:  float
    qty:          int
    opened_at:    str           # ISO timestamp
    conviction:   float = 0.0
    score:        int = 0


@dataclass
class MonitorAction:
    """Result of evaluating one open position."""
    ticker:        str
    action:        str           # "hold" | "close_stop" | "close_tp" | "error"
    reason:        str
    entry_price:   float
    current_price: float
    stop_loss:     float
    take_profit:   float
    pnl_pct:       float         # unrealized P&L %
    pnl_usd:       float
    order_result:  Optional[OrderResult] = None

    @property
    def closed(self) -> bool:
        return self.action in ("close_stop", "close_tp") and (
            self.order_result is not None and self.order_result.success
        )


# ── Position log persistence ──────────────────────────────────────────────────

def load_position_log() -> Dict[str, PositionRecord]:
    """Load stored position metadata from disk. Returns {ticker: PositionRecord}."""
    if not POSITION_LOG.exists():
        return {}
    try:
        raw = json.loads(POSITION_LOG.read_text())
        return {k: PositionRecord(**v) for k, v in raw.items()}
    except Exception as e:
        log.warning("position_log load failed: %s", e)
        return {}


def save_position_log(records: Dict[str, PositionRecord]) -> None:
    """Persist position metadata to disk."""
    try:
        POSITION_LOG.write_text(
            json.dumps({k: asdict(v) for k, v in records.items()}, indent=2)
        )
    except Exception as e:
        log.warning("position_log save failed: %s", e)


def record_new_position(
    ticker:      str,
    side:        str,
    entry_price: float,
    stop_loss:   float,
    take_profit: float,
    qty:         int,
    conviction:  float = 0.0,
    score:       int = 0,
) -> None:
    """
    Called by trade_engine after a successful order to store position metadata.
    This is what makes stop/TP monitoring possible between scans.
    """
    records = load_position_log()
    records[ticker] = PositionRecord(
        ticker=ticker,
        side=side,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        qty=qty,
        opened_at=datetime.now().isoformat(),
        conviction=conviction,
        score=score,
    )
    save_position_log(records)
    log.info("Position recorded: %s %s @ $%.2f stop=$%.2f tp=$%.2f",
             side.upper(), ticker, entry_price, stop_loss, take_profit)


def remove_position_record(ticker: str) -> None:
    """Remove a position record after it's been closed."""
    records = load_position_log()
    if ticker in records:
        del records[ticker]
        save_position_log(records)
        log.debug("Position record removed: %s", ticker)


# ── Evaluation logic ──────────────────────────────────────────────────────────

def _evaluate_position(
    position: Position,
    record:   PositionRecord,
    dry_run:  bool,
    client:   AlpacaClient,
) -> MonitorAction:
    """
    Compare current price against stored stop/TP and decide whether to close.
    """
    price  = position.current_price
    entry  = record.entry_price
    stop   = record.stop_loss
    tp     = record.take_profit
    side   = record.side

    pnl_usd = (price - entry) * position.qty if side == "long" else (entry - price) * position.qty
    pnl_pct = ((price - entry) / entry * 100) if side == "long" else ((entry - price) / entry * 100)

    # ── Long position checks ──────────────────────────────────────────────────
    if side == "long":
        if price <= stop:
            reason = f"Stop hit: ${price:.2f} ≤ stop ${stop:.2f} | P&L: {pnl_pct:+.2f}%"
            action = "close_stop"
        elif price >= tp:
            reason = f"TP hit: ${price:.2f} ≥ target ${tp:.2f} | P&L: {pnl_pct:+.2f}%"
            action = "close_tp"
        else:
            pct_to_stop = (price - stop) / stop * 100
            pct_to_tp   = (tp - price) / price * 100
            return MonitorAction(
                ticker=record.ticker, action="hold",
                reason=f"Holding — ${price:.2f} | {pct_to_stop:.1f}% above stop | {pct_to_tp:.1f}% below TP",
                entry_price=entry, current_price=price,
                stop_loss=stop, take_profit=tp,
                pnl_pct=round(pnl_pct, 2), pnl_usd=round(pnl_usd, 2),
            )

    # ── Short position checks ─────────────────────────────────────────────────
    else:
        if price >= stop:
            reason = f"Stop hit: ${price:.2f} ≥ stop ${stop:.2f} | P&L: {pnl_pct:+.2f}%"
            action = "close_stop"
        elif price <= tp:
            reason = f"TP hit: ${price:.2f} ≤ target ${tp:.2f} | P&L: {pnl_pct:+.2f}%"
            action = "close_tp"
        else:
            pct_to_stop = (stop - price) / price * 100
            pct_to_tp   = (price - tp) / tp * 100
            return MonitorAction(
                ticker=record.ticker, action="hold",
                reason=f"Holding — ${price:.2f} | {pct_to_stop:.1f}% below stop | {pct_to_tp:.1f}% above TP",
                entry_price=entry, current_price=price,
                stop_loss=stop, take_profit=tp,
                pnl_pct=round(pnl_pct, 2), pnl_usd=round(pnl_usd, 2),
            )

    # ── Execute close ─────────────────────────────────────────────────────────
    log.warning("MONITOR → %s %s: %s", action.upper(), record.ticker, reason)

    result: Optional[OrderResult] = None
    if not dry_run:
        result = client.close_position(record.ticker)
        if result.success:
            remove_position_record(record.ticker)
            log.info("Closed %s: %s", record.ticker, reason)
            # Record to P&L ledger
            try:
                record_trade(
                    ticker       = record.ticker,
                    company_name = "",          # populated in scanner; blank here
                    side         = record.side,
                    entry_price  = record.entry_price,
                    exit_price   = position.current_price,
                    qty          = record.qty,
                    entry_stop   = record.stop_loss,
                    entry_tp     = record.take_profit,
                    exit_reason  = "stop" if action == "close_stop" else "take_profit",
                    opened_at    = record.opened_at,
                    conviction   = record.conviction,
                    score        = record.score,
                )
            except Exception as e:
                log.debug("P&L record failed: %s", e)
        else:
            log.error("Failed to close %s: %s", record.ticker, result.message)
    else:
        log.info("DRY RUN: Would close %s — %s", record.ticker, reason)

    return MonitorAction(
        ticker=record.ticker, action=action, reason=reason,
        entry_price=entry, current_price=price,
        stop_loss=stop, take_profit=tp,
        pnl_pct=round(pnl_pct, 2), pnl_usd=round(pnl_usd, 2),
        order_result=result,
    )


# ── Main entry point ──────────────────────────────────────────────────────────

def run_position_monitor(dry_run: bool = False) -> List[MonitorAction]:
    """
    Run stop/TP check on all open positions with stored records.
    Called at the start of each scan run in main.py.

    Returns list of MonitorAction (one per position with stored metadata).
    Empty list if no positions or Alpaca not configured.
    """
    client = get_client()
    if not client.ready:
        log.debug("Position monitor: Alpaca not configured — skipping")
        return []

    records = load_position_log()
    if not records:
        log.debug("Position monitor: no stored position records")
        return []

    positions = {p.symbol: p for p in client.get_positions()}
    if not positions:
        # No open positions — clean up stale records
        stale = list(records.keys())
        if stale:
            log.info("Position monitor: %d stale records cleaned (no open positions)", len(stale))
            save_position_log({})
        return []

    actions: List[MonitorAction] = []
    log.info("Position monitor: checking %d stored positions against %d open",
             len(records), len(positions))

    for ticker, record in records.items():
        if ticker not in positions:
            # Position closed externally (e.g. Alpaca bracket triggered)
            log.info("%s: position closed externally — removing record", ticker)
            remove_position_record(ticker)
            continue

        action = _evaluate_position(positions[ticker], record, dry_run, client)
        actions.append(action)
        log.info(
            "MONITOR %s: %s | entry=$%.2f cur=$%.2f P&L=%+.2f%% ($%+.2f)",
            ticker, action.action.upper(),
            action.entry_price, action.current_price,
            action.pnl_pct, action.pnl_usd,
        )

    closed  = sum(1 for a in actions if a.closed)
    holding = sum(1 for a in actions if a.action == "hold")
    log.info("Monitor complete: %d closed, %d holding", closed, holding)

    return actions
