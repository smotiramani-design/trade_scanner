"""
daily/run.py — entry points for the daily scanner (CLI + AWS Lambda ready).

Two jobs per trading day (ET, Mon–Fri):
  09:15  scan      → store top 10 long / top 10 short with whole-day Fib targets
  16:00  validate  → mark each whole-day target hit / missed

The exact AWS wiring (EventBridge rules, packaging) is intentionally left thin here
so we can shape the Lambda logic together. `handler` already dispatches correctly by
ET clock or an explicit event["mode"], so it can be dropped into a Lambda as-is.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
log = logging.getLogger(__name__)


def run_daily_scan_job(universe: Optional[str] = None, top_n: int = 10,
                       run_time: Optional[datetime] = None) -> dict:
    """9:15 job — scan + persist top 10 long / 10 short."""
    from daily.scanner import run_daily_scan
    return run_daily_scan(universe=universe, top_n=top_n, run_time=run_time)


def run_daily_validation_job(trade_date=None) -> dict:
    """4 PM job — validate whole-day Fib targets."""
    from daily.validate import validate_daily_targets
    return validate_daily_targets(trade_date=trade_date)


def handler(event=None, context=None) -> dict:
    """
    AWS Lambda handler. Dispatch order:
      1. explicit event["mode"] == "scan" | "validate"
      2. otherwise by ET clock: afternoon (>= 12:00) → validate, else → scan

    event overrides:
      {"mode": "scan"|"validate"}   force a specific job
      {"force": true}               bypass the holiday skip
      {"universe": "..."}           override the scan universe
      {"top_n": 10}                 longs/shorts to keep
    """
    event = event or {}
    from utils.holidays import is_market_holiday
    from utils.logger import setup_logging
    setup_logging()

    now_et = datetime.now(ET)
    force = bool(event.get("force"))

    if not force and is_market_holiday(now_et.date()):
        log.info("NYSE holiday (%s) — skipping daily job.", now_et.date())
        return {"status": "skipped", "reason": "holiday", "et": now_et.isoformat()}

    mode = event.get("mode") or ("validate" if now_et.hour >= 12 else "scan")

    if mode == "scan":
        result = run_daily_scan_job(
            universe=event.get("universe"),
            top_n=int(event.get("top_n") or 10),
            run_time=now_et,
        )
    elif mode == "validate":
        result = run_daily_validation_job()
    else:
        return {"status": "error", "reason": f"unknown mode '{mode}'"}

    result["mode"] = mode
    result["et"] = now_et.isoformat()
    return result


# AWS Lambda default handler alias.
lambda_handler = handler
