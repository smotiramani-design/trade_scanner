"""
utils/position_monitor.py — ENH-13: Position close logic.

Tracks open positions in positions.json on disk. A separate monitoring
loop (run via monitor.py) checks live prices every N minutes between
scans and fires email/SMS alerts when T1 or stop is hit.

Schema for positions.json:
{
  "positions": [
    {
      "id":          "EXC_20260612_134451",   # unique ID
      "ticker":      "EXC",
      "direction":   "bullish",               # "bullish" | "bearish"
      "entry":       46.04,                   # Fib 38.2% entry price
      "stop":        45.82,                   # Fib 61.8% stop
      "t1":          46.40,                   # Fib 100% T1
      "t2":          46.66,                   # Fib 127.2% T2
      "t3":          46.98,                   # Fib 161.8% T3
      "score":       7,
      "grade":       "B",
      "opened_at":   "2026-06-12T13:44:51",
      "closed_at":   null,
      "close_reason": null,                   # "T1_HIT" | "STOP_HIT" | "MANUAL"
      "close_price":  null,
      "status":      "open"                   # "open" | "closed"
    }
  ]
}
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import config

log = logging.getLogger(__name__)

POSITIONS_FILE = Path(os.getenv("POSITIONS_FILE", "positions.json"))
MONITOR_INTERVAL_SEC = int(os.getenv("MONITOR_INTERVAL_SEC", "300"))   # 5 min default


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class Position:
    id:           str
    ticker:       str
    direction:    str          # "bullish" | "bearish"
    entry:        float
    stop:         float
    t1:           float
    t2:           float
    t3:           float
    score:        int
    grade:        str
    opened_at:    str          # ISO-8601
    closed_at:    Optional[str]   = None
    close_reason: Optional[str]   = None   # "T1_HIT" | "STOP_HIT" | "MANUAL"
    close_price:  Optional[float] = None
    status:       str              = "open"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── File I/O ──────────────────────────────────────────────────────────────────

def _load() -> List[Position]:
    """Load all positions from disk. Returns [] if file doesn't exist yet."""
    if not POSITIONS_FILE.exists():
        return []
    try:
        data = json.loads(POSITIONS_FILE.read_text())
        return [Position.from_dict(p) for p in data.get("positions", [])]
    except Exception as e:
        log.error("Failed to load positions file: %s", e)
        return []


def _save(positions: List[Position]) -> None:
    """Persist all positions to disk atomically."""
    try:
        tmp = POSITIONS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(
            {"positions": [p.to_dict() for p in positions]},
            indent=2,
        ))
        tmp.replace(POSITIONS_FILE)
    except Exception as e:
        log.error("Failed to save positions file: %s", e)


# ── Public API ────────────────────────────────────────────────────────────────

def open_positions() -> List[Position]:
    """Return all currently open positions."""
    return [p for p in _load() if p.status == "open"]


def closed_positions() -> List[Position]:
    """Return all closed positions (historical log)."""
    return [p for p in _load() if p.status == "closed"]


def add_position(
    ticker:    str,
    direction: str,
    entry:     float,
    stop:      float,
    t1:        float,
    t2:        float,
    t3:        float,
    score:     int,
    grade:     str,
) -> Position:
    """
    Record a new open position. Called by scanner.py after each top pick
    is emitted. Skips if ticker already has an open position.
    Returns the Position object (new or existing).
    """
    all_pos = _load()
    existing = next((p for p in all_pos if p.ticker == ticker and p.status == "open"), None)
    if existing:
        log.info("Position already open for %s — skipping duplicate entry", ticker)
        return existing

    ts  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    pos = Position(
        id        = f"{ticker}_{ts}",
        ticker    = ticker,
        direction = direction,
        entry     = entry,
        stop      = stop,
        t1        = t1,
        t2        = t2,
        t3        = t3,
        score     = score,
        grade     = grade,
        opened_at = datetime.now(timezone.utc).isoformat(),
    )
    all_pos.append(pos)
    _save(all_pos)
    log.info("Position opened: %s %s entry=%.2f stop=%.2f t1=%.2f",
             ticker, direction, entry, stop, t1)
    return pos


def close_position(pos: Position, reason: str, close_price: float) -> None:
    """
    Mark a position as closed. reason: 'T1_HIT' | 'STOP_HIT' | 'MANUAL'.
    """
    all_pos = _load()
    for p in all_pos:
        if p.id == pos.id:
            p.status       = "closed"
            p.close_reason = reason
            p.close_price  = close_price
            p.closed_at    = datetime.now(timezone.utc).isoformat()
            log.info("Position closed: %s reason=%s price=%.2f", p.ticker, reason, close_price)
            break
    _save(all_pos)


def close_position_manual(ticker: str) -> bool:
    """
    Manually close an open position by ticker. Returns True if found and closed.
    """
    all_pos = _load()
    found   = False
    for p in all_pos:
        if p.ticker == ticker and p.status == "open":
            p.status       = "closed"
            p.close_reason = "MANUAL"
            p.closed_at    = datetime.now(timezone.utc).isoformat()
            found          = True
            log.info("Position manually closed: %s", ticker)
    if found:
        _save(all_pos)
    return found


# ── Price checking ────────────────────────────────────────────────────────────

def _get_live_prices(tickers: List[str]) -> dict:
    """
    Fetch live prices for a list of tickers via FMP batch quote.
    Returns {ticker: price} — empty dict on failure.
    """
    try:
        from data.fmp_client import get_batch_quotes
        quotes = get_batch_quotes(tickers)
        return {t: q.get("price", 0.0) for t, q in quotes.items() if q.get("price")}
    except Exception as e:
        log.error("Live price fetch failed: %s", e)
        return {}


def check_positions() -> List[dict]:
    """
    Check all open positions against live prices.
    Returns list of alert dicts for positions that hit T1 or stop.
    Called by the monitor loop.
    """
    positions = open_positions()
    if not positions:
        log.debug("No open positions to monitor")
        return []

    tickers = [p.ticker for p in positions]
    prices  = _get_live_prices(tickers)
    alerts  = []

    for pos in positions:
        price = prices.get(pos.ticker)
        if not price:
            log.warning("No live price for %s — skipping check", pos.ticker)
            continue

        hit_t1   = False
        hit_stop = False

        if pos.direction == "bullish":
            hit_t1   = price >= pos.t1
            hit_stop = price <= pos.stop
        elif pos.direction == "bearish":
            hit_t1   = price <= pos.t1
            hit_stop = price >= pos.stop

        if hit_t1:
            close_position(pos, "T1_HIT", price)
            pnl_pct = (price - pos.entry) / pos.entry * 100 if pos.direction == "bullish" \
                      else (pos.entry - price) / pos.entry * 100
            alerts.append({
                "ticker":    pos.ticker,
                "event":     "T1_HIT",
                "direction": pos.direction,
                "entry":     pos.entry,
                "price":     price,
                "t1":        pos.t1,
                "stop":      pos.stop,
                "pnl_pct":   pnl_pct,
                "grade":     pos.grade,
                "score":     pos.score,
            })
            log.info("T1 HIT: %s @ %.2f (entry %.2f, pnl %.1f%%)",
                     pos.ticker, price, pos.entry, pnl_pct)

        elif hit_stop:
            close_position(pos, "STOP_HIT", price)
            pnl_pct = (price - pos.entry) / pos.entry * 100 if pos.direction == "bullish" \
                      else (pos.entry - price) / pos.entry * 100
            alerts.append({
                "ticker":    pos.ticker,
                "event":     "STOP_HIT",
                "direction": pos.direction,
                "entry":     pos.entry,
                "price":     price,
                "t1":        pos.t1,
                "stop":      pos.stop,
                "pnl_pct":   pnl_pct,
                "grade":     pos.grade,
                "score":     pos.score,
            })
            log.info("STOP HIT: %s @ %.2f (entry %.2f, pnl %.1f%%)",
                     pos.ticker, price, pos.entry, pnl_pct)

        else:
            dist_t1   = abs(price - pos.t1)   / pos.t1   * 100
            dist_stop = abs(price - pos.stop) / pos.stop * 100
            log.debug("%s @ %.2f — %.1f%% from T1, %.1f%% from stop",
                      pos.ticker, price, dist_t1, dist_stop)

    return alerts


# ── Alert formatting ──────────────────────────────────────────────────────────

def format_alert_email(alerts: List[dict]) -> str:
    """Build HTML email body for position close alerts."""
    if not alerts:
        return ""

    rows = []
    for a in alerts:
        is_t1      = a["event"] == "T1_HIT"
        is_bull    = a["direction"] == "bullish"
        pnl_color  = "#1D6F42" if a["pnl_pct"] >= 0 else "#9C0006"
        event_icon = "✅ T1 Hit" if is_t1 else "🛑 Stop Hit"
        event_bg   = "#E8F5E9" if is_t1 else "#FFF5F5"
        dir_arrow  = "▲" if is_bull else "▼"

        rows.append(f"""
        <tr style="background:{event_bg}">
          <td style="padding:10px;font-weight:bold;font-size:15px">{dir_arrow} {a['ticker']}</td>
          <td style="padding:10px">{event_icon}</td>
          <td style="padding:10px">${a['entry']:.2f}</td>
          <td style="padding:10px;font-weight:bold">${a['price']:.2f}</td>
          <td style="padding:10px;color:{pnl_color};font-weight:bold">{a['pnl_pct']:+.1f}%</td>
          <td style="padding:10px">${a['t1']:.2f}</td>
          <td style="padding:10px">${a['stop']:.2f}</td>
          <td style="padding:10px">{a['grade']} ({a['score']:+d})</td>
        </tr>""")

    return f"""
    <div style="font-family:Arial,sans-serif;max-width:800px;margin:0 auto">
      <h2 style="color:#2E75B6">📊 Position Alert — {datetime.now().strftime('%b %d, %Y %H:%M ET')}</h2>
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead>
          <tr style="background:#2E75B6;color:white">
            <th style="padding:10px;text-align:left">Ticker</th>
            <th style="padding:10px;text-align:left">Event</th>
            <th style="padding:10px;text-align:left">Entry</th>
            <th style="padding:10px;text-align:left">Exit Price</th>
            <th style="padding:10px;text-align:left">P&L</th>
            <th style="padding:10px;text-align:left">T1</th>
            <th style="padding:10px;text-align:left">Stop</th>
            <th style="padding:10px;text-align:left">Grade</th>
          </tr>
        </thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
      <p style="color:#666;font-size:11px;margin-top:16px">
        Educational purposes only. Not financial advice.
      </p>
    </div>"""


def format_alert_sms(alerts: List[dict]) -> str:
    """Build compact SMS string for position close alerts."""
    lines = []
    for a in alerts:
        icon = "✅" if a["event"] == "T1_HIT" else "🛑"
        lines.append(
            f"{icon} {a['ticker']} {a['event'].replace('_', ' ')} "
            f"@ ${a['price']:.2f} (entry ${a['entry']:.2f}, {a['pnl_pct']:+.1f}%)"
        )
    return "\n".join(lines)
