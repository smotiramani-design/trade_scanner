"""
monitor.py — ENH-13: Position monitoring loop.

Run this in a separate terminal (or as a background process) while the
main scanner is active. It checks open positions every MONITOR_INTERVAL_SEC
seconds (default: 300 = 5 min) and fires email + SMS alerts when T1 or
stop is hit.

Usage:
    python monitor.py                    # runs indefinitely, 5-min interval
    python monitor.py --interval 60      # check every 60 seconds
    python monitor.py --once             # single check then exit (for cron)
    python monitor.py --list             # print open positions and exit

The main scanner (main.py) calls add_position() automatically for each
top-5 bullish/bearish pick. This monitor handles the close side.

Runs only during market hours (9:30–16:00 ET Mon–Fri) unless --force is passed.
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

import config
from utils.position_monitor import (
    MONITOR_INTERVAL_SEC,
    check_positions,
    close_position_manual,
    format_alert_email,
    format_alert_sms,
    open_positions,
    closed_positions,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("monitor")

_RUNNING = True


def _signal_handler(sig, frame):
    global _RUNNING
    log.info("Shutdown signal received — stopping monitor")
    _RUNNING = False


signal.signal(signal.SIGINT,  _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ── Market hours guard ────────────────────────────────────────────────────────

def _is_market_hours() -> bool:
    """Return True if current time is within NYSE market hours (9:30–16:00 ET Mon–Fri)."""
    try:
        import pytz
        et  = pytz.timezone("America/New_York")
        now = datetime.now(et)
        if now.weekday() >= 5:   # Saturday=5, Sunday=6
            return False
        open_t  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
        close_t = now.replace(hour=16, minute=0,  second=0, microsecond=0)
        return open_t <= now <= close_t
    except ImportError:
        # pytz not installed — skip guard
        return True


# ── Alert dispatch ────────────────────────────────────────────────────────────

def _send_alerts(alerts: list) -> None:
    """Fire email + SMS for any position alerts."""
    if not alerts:
        return

    # Email
    try:
        from utils.email_sender import send_raw_html
        html = format_alert_email(alerts)
        tickers = ", ".join(a["ticker"] for a in alerts)
        subject = f"[Position Alert] {tickers} — {len(alerts)} close(s)"
        send_raw_html(subject=subject, html_body=html)
        log.info("Alert email sent for: %s", tickers)
    except Exception as e:
        log.error("Failed to send alert email: %s", e)

    # SMS
    try:
        from utils.sms_sender import send_sms
        body = format_alert_sms(alerts)
        send_sms(body)
        log.info("Alert SMS sent")
    except Exception as e:
        log.error("Failed to send alert SMS: %s", e)


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_list() -> None:
    """Print all open positions to stdout."""
    positions = open_positions()
    if not positions:
        print("No open positions.")
        return
    print(f"\n{'─'*70}")
    print(f"  {'TICKER':<8} {'DIR':<10} {'ENTRY':>8} {'STOP':>8} {'T1':>8} {'T2':>8}  GRADE")
    print(f"{'─'*70}")
    for p in positions:
        arrow = "▲" if p.direction == "bullish" else "▼"
        print(f"  {arrow} {p.ticker:<6} {p.direction:<10} "
              f"{p.entry:>8.2f} {p.stop:>8.2f} {p.t1:>8.2f} {p.t2:>8.2f}  "
              f"{p.grade} ({p.score:+d})  opened {p.opened_at[:16]}")
    print(f"{'─'*70}")
    print(f"  {len(positions)} open position(s)\n")

    history = closed_positions()
    if history:
        print(f"  Last 5 closed:")
        for p in history[-5:]:
            pnl = ""
            if p.close_price and p.entry:
                raw = (p.close_price - p.entry) / p.entry * 100
                pnl = f"{raw:+.1f}%"
            icon = "✅" if p.close_reason == "T1_HIT" else "🛑" if p.close_reason == "STOP_HIT" else "🔧"
            print(f"    {icon} {p.ticker:<6} {p.close_reason or 'MANUAL':<12} "
                  f"entry={p.entry:.2f} exit={p.close_price or 0:.2f} {pnl}")
        print()


def cmd_close(ticker: str) -> None:
    """Manually close a position by ticker."""
    ok = close_position_manual(ticker.upper())
    if ok:
        print(f"✅ Position for {ticker.upper()} manually closed.")
    else:
        print(f"⚠  No open position found for {ticker.upper()}.")


def cmd_once(force: bool = False) -> None:
    """Single check pass — used for cron."""
    if not force and not _is_market_hours():
        log.info("Outside market hours — skipping check (use --force to override)")
        return
    log.info("Running single position check pass…")
    alerts = check_positions()
    if alerts:
        _send_alerts(alerts)
        log.info("%d alert(s) fired", len(alerts))
    else:
        log.info("No positions hit T1 or stop")


def cmd_loop(interval: int, force: bool = False) -> None:
    """Run continuous monitoring loop until SIGINT/SIGTERM."""
    log.info("Position monitor started — interval %ds, checking %d open position(s)",
             interval, len(open_positions()))
    while _RUNNING:
        if force or _is_market_hours():
            try:
                alerts = check_positions()
                if alerts:
                    _send_alerts(alerts)
            except Exception as e:
                log.error("Unexpected error in check loop: %s", e)
        else:
            log.debug("Outside market hours — sleeping")

        # Sleep in 1s chunks so SIGINT is handled promptly
        for _ in range(interval):
            if not _RUNNING:
                break
            time.sleep(1)

    log.info("Monitor stopped.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Position close monitor (ENH-13)")
    parser.add_argument("--interval",  type=int, default=MONITOR_INTERVAL_SEC,
                        help="Check interval in seconds (default: 300)")
    parser.add_argument("--once",      action="store_true",
                        help="Run one check pass then exit")
    parser.add_argument("--list",      action="store_true",
                        help="Print open positions and exit")
    parser.add_argument("--close",     type=str, metavar="TICKER",
                        help="Manually close a position by ticker")
    parser.add_argument("--force",     action="store_true",
                        help="Run even outside market hours")
    args = parser.parse_args()

    if args.list:
        cmd_list()
    elif args.close:
        cmd_close(args.close)
    elif args.once:
        cmd_once(force=args.force)
    else:
        cmd_loop(interval=args.interval, force=args.force)


if __name__ == "__main__":
    main()
