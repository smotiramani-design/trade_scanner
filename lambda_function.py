"""
lambda_function.py — AWS Lambda entry point for the Trading Signal Scanner.

One Lambda, scheduled hourly by EventBridge at :35 past the hour, 9:35 AM–3:35 PM
ET, Mon–Fri. Whether it ALSO executes trades is decided here in Python based on
the Eastern-time clock — no second schedule needed.

Trade windows (ET):  9:35 AM, 11:35 AM, 2:35 PM  → trading enabled
All other hours                                  → scan only (write to DB)

EventBridge Scheduler should be created with timezone "America/New_York" and a
cron of:  cron(35 9-15 ? * MON-FRI *)   (DST handled automatically by AWS).

Optional `event` overrides (handy for manual test invokes from the console):
    {"trade": true}      force trading on/off, ignoring the clock
    {"force": true}      bypass the holiday / market-hours skip guard
    {"universe": "..."}  override the scan universe (default: config.DEFAULT_UNIVERSE)
    {"top_n": 5}         override number of top picks
    {"dry_run": true}    evaluate trades but don't submit orders

Config/secrets:
    Set the env var SECRET_NAME to an AWS Secrets Manager secret (a JSON of
    key/value pairs) and it is loaded into the environment at cold start, before
    `config` reads it. Real Lambda env vars take precedence over secret values.
"""
from __future__ import annotations

import os


def _hydrate_env_from_secrets() -> None:
    """Load a Secrets Manager secret (JSON key/values) into os.environ.

    Runs BEFORE `import config` because config reads env vars at import time.
    No-op unless the SECRETS_NAME (or SECRET_ARN) env var is set, so local runs
    and plain-env-var setups are unaffected. boto3 ships with the Lambda runtime.
    """
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
            os.environ.setdefault(key, str(value))   # real env vars win over secret


_hydrate_env_from_secrets()

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import config
from utils.logger import setup_logging
from utils.holidays import is_market_holiday

ET = ZoneInfo("America/New_York")
TRADE_HOURS = {9, 11, 14}            # 9:35 AM, 11:35 AM, 2:35 PM ET
MARKET_OPEN_MIN = 9 * 60 + 30        # 9:30 AM
MARKET_CLOSE_MIN = 16 * 60           # 4:00 PM

log = logging.getLogger(__name__)


def _should_trade(now_et: datetime, event: dict) -> bool:
    """Trade only in the 9 / 11 / 14 ET hours, unless the event overrides it."""
    if "trade" in event:
        return bool(event["trade"])
    return now_et.hour in TRADE_HOURS


def _in_market_hours(now_et: datetime) -> bool:
    if now_et.weekday() > 4:                 # Sat/Sun
        return False
    mins = now_et.hour * 60 + now_et.minute
    return MARKET_OPEN_MIN <= mins <= MARKET_CLOSE_MIN


def lambda_handler(event, context):
    event = event or {}
    setup_logging()

    now_et = datetime.now(ET)
    force = bool(event.get("force"))

    # ── Skip guards (holidays + outside market hours) ─────────────────────────
    if not force:
        if is_market_holiday(now_et.date()):
            log.info("NYSE holiday (%s) — skipping.", now_et.date())
            return {"status": "skipped", "reason": "holiday", "et": now_et.isoformat()}
        if not _in_market_hours(now_et):
            log.info("Outside market hours (%s ET) — skipping.", now_et.strftime("%H:%M"))
            return {"status": "skipped", "reason": "outside_market_hours",
                    "et": now_et.isoformat()}

    do_trade = _should_trade(now_et, event)
    universe = event.get("universe") or config.DEFAULT_UNIVERSE
    top_n = int(event.get("top_n") or config.TOP_N_PICKS)
    dry_run = bool(event.get("dry_run", False)) or not config.TRADE_ENABLED

    log.info("Run start: %s ET · universe=%s · trade=%s · dry_run=%s",
             now_et.strftime("%Y-%m-%d %H:%M"), universe, do_trade, dry_run)

    # ── Imports deferred so the heavy data libs load only inside the run ──────
    from scanner import resolve_universe, scan, record_top_picks
    from signals.conviction import top_picks

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

    # ── Trading (only during the 9 / 11 / 14 ET windows) ──────────────────────
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

    # ── Persist to the database (replaces the hourly email) ───────────────────
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
        "et": now_et.isoformat(),
        "universe": universe,
        "mode": mode,
        "analyzed": len(results),
        "bulls": len(bulls),
        "bears": len(bears),
        "traded": do_trade,
        "dry_run": dry_run,
        "scan_id": scan_id,
    }


if __name__ == "__main__":
    # Local smoke test:  python lambda_function.py
    print(lambda_handler({"force": True, "trade": False, "dry_run": True}, None))
