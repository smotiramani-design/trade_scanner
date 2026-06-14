"""
lambda_function.py — AWS Lambda entry point for the Trading Signal Scanner.

Schedule (America/New_York, Mon–Fri) — one EventBridge rule at the top of each hour:
  cron(0 10-16 ? * MON-FRI *)

  10 AM, 11 AM, 12 PM, 1 PM, 2 PM, 3 PM  →  scan (+ trade at 10 AM, 12 PM, 2 PM)
  4 PM  →  Fib target hit validation only (no scan, no trades)

Optional `event` overrides (manual test invokes):
    {"force": true}      bypass holiday / schedule skip
    {"mode": "scan"}     force scan path
    {"mode": "trade"}    force trade path (scan + trade)
    {"mode": "fib"}      force end-of-day fib validation
    {"trade": true/false} override trade decision on scan/trade runs
    {"universe": "..."}  override scan universe
    {"top_n": 5}
    {"dry_run": true}

Config/secrets: set SECRET_NAME to a Secrets Manager JSON secret (loaded at cold start).
"""
from __future__ import annotations

import os


def _hydrate_env_from_secrets() -> None:
    secret_name = (os.getenv("SECRET_NAME") or os.getenv("SECRETS_NAME")
                   or os.getenv("SECRET_ARN"))
    if not secret_name:
        return
    import json
    import boto3

    raw = boto3.client("secretsmanager").get_secret_value(SecretId=secret_name).get("SecretString")
    if not raw:
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return
    for key, value in (data or {}).items():
        if value is not None:
            os.environ.setdefault(key, str(value))


_hydrate_env_from_secrets()

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import config
from utils.logger import setup_logging
from utils.holidays import is_market_holiday

ET = ZoneInfo("America/New_York")

# Session window for scheduled jobs (10:00 AM – 4:00 PM ET)
SESSION_START_MIN = 10 * 60          # 10:00 AM
SESSION_END_MIN   = 16 * 60          # 4:00 PM

# Hourly scans: 10 AM – 3 PM (top of hour)
SCAN_START_HOUR = 10
SCAN_END_HOUR   = 15

# Trades on the same top-of-hour run as the scan
TRADE_HOURS = {10, 12, 14}   # 10 AM, 12 PM, 2 PM ET

# End-of-day Fib validation: 4 PM only
FIB_VALIDATION_HOUR = 16

log = logging.getLogger(__name__)


def _run_kind(now_et: datetime) -> str:
    """Return 'fib' | 'scan' | 'skip' based on ET clock (top of hour only)."""
    if now_et.minute != 0:
        return "skip"
    h = now_et.hour
    if h == FIB_VALIDATION_HOUR:
        return "fib"
    if SCAN_START_HOUR <= h <= SCAN_END_HOUR:
        return "scan"
    return "skip"


def _in_session_window(now_et: datetime) -> bool:
    """True during 10:00 AM – 4:00 PM ET on weekdays."""
    if now_et.weekday() > 4:
        return False
    mins = now_et.hour * 60 + now_et.minute
    return SESSION_START_MIN <= mins <= SESSION_END_MIN


def _should_trade(now_et: datetime, event: dict) -> bool:
    if "trade" in event:
        return bool(event["trade"])
    return now_et.hour in TRADE_HOURS


def _run_scan_and_maybe_trade(now_et: datetime, event: dict, do_trade: bool) -> dict:
    from scanner import resolve_universe, scan, record_top_picks
    from signals.conviction import top_picks

    universe = event.get("universe") or config.DEFAULT_UNIVERSE
    top_n = int(event.get("top_n") or config.TOP_N_PICKS)
    dry_run = bool(event.get("dry_run", False)) or not config.TRADE_ENABLED

    ticker_list = resolve_universe(universe, config.MAX_TICKERS)
    if config.PERSONAL_WATCHLIST:
        extra = [t for t in config.PERSONAL_WATCHLIST if t not in ticker_list]
        ticker_list = extra + ticker_list
    if not ticker_list:
        log.error("No tickers resolved for universe '%s'.", universe)
        return {"status": "error", "reason": "no_tickers", "universe": universe}

    results = scan(ticker_list)
    if not results:
        log.error("Scan returned no results (check FMP key / tickers).")
        return {"status": "error", "reason": "no_results"}

    bulls, bears = top_picks(results, top_n)
    mode = results[0].mode
    session = "open" if mode == "Hourly" else "closed"

    try:
        record_top_picks(bulls, bears)
    except Exception:
        log.warning("record_top_picks failed (non-fatal).", exc_info=True)

    bull_decisions, bear_decisions = [], []
    if do_trade:
        if not config.ALPACA_ENABLED:
            log.warning("Trade window but Alpaca not configured — skipping trades.")
        else:
            from trading import run_trade_session
            bull_decisions, bear_decisions, _acct = run_trade_session(
                bulls, bears, dry_run=dry_run
            )
            executed = sum(1 for d in bull_decisions + bear_decisions if d.executed)
            log.info("Trade session: %d executed (dry_run=%s).", executed, dry_run)

    scan_id = None
    if config.DB_ENABLED:
        try:
            from utils.db_writer import write_scan
            scan_id = write_scan(
                results, bulls, bears, bull_decisions, bear_decisions,
                session=session, universe=universe, mode=mode,
                trade_run=do_trade, dry_run=dry_run,
            )
        except Exception:
            log.exception("DB write failed (non-fatal for the run).")
    else:
        log.warning("DB_ENABLED=false — results not persisted. Set DATABASE_URL.")

    return {
        "status": "ok",
        "mode": "trade" if do_trade else "scan",
        "et": now_et.isoformat(),
        "universe": universe,
        "scan_mode": mode,
        "analyzed": len(results),
        "bulls": len(bulls),
        "bears": len(bears),
        "traded": do_trade,
        "dry_run": dry_run,
        "scan_id": scan_id,
    }


def lambda_handler(event, context):
    event = event or {}
    setup_logging()

    now_et = datetime.now(ET)
    force = bool(event.get("force"))
    forced_mode = event.get("mode")

    if forced_mode == "fib":
        kind = "fib"
    elif forced_mode in ("scan", "trade"):
        kind = "scan"
    else:
        kind = _run_kind(now_et)

    if not force:
        if is_market_holiday(now_et.date()):
            log.info("NYSE holiday (%s) — skipping.", now_et.date())
            return {"status": "skipped", "reason": "holiday", "et": now_et.isoformat()}
        if kind == "skip":
            log.info("Not a scheduled run slot (%s ET) — skipping.", now_et.strftime("%H:%M"))
            return {"status": "skipped", "reason": "not_scheduled",
                    "et": now_et.isoformat()}
        if not _in_session_window(now_et):
            log.info("Outside session window (%s ET) — skipping.", now_et.strftime("%H:%M"))
            return {"status": "skipped", "reason": "outside_session",
                    "et": now_et.isoformat()}

    log.info("Run start: %s ET · kind=%s · force=%s",
             now_et.strftime("%Y-%m-%d %H:%M"), kind, force)

    if kind == "fib":
        from utils.fib_validation import validate_today_fib_hits
        result = validate_today_fib_hits(now_et.date())
        result["et"] = now_et.isoformat()
        result["mode"] = "fib"
        return result

    if forced_mode == "trade":
        do_trade = True
    elif forced_mode == "scan":
        do_trade = bool(event.get("trade", False))
    else:
        do_trade = _should_trade(now_et, event)
    return _run_scan_and_maybe_trade(now_et, event, do_trade)


if __name__ == "__main__":
    print(lambda_handler({"force": True, "mode": "fib"}, None))
