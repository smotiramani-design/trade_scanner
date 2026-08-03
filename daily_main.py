"""
daily_main.py — CLI for the daily conviction + Fibonacci scanner.

The daily scan reuses the intraday 10-signal + market-sentiment + Fibonacci engine
on DAILY bars and produces the top 10 longs and top 10 shorts, each with a whole-day
(9:15 → 4 PM) Fibonacci target. A separate 4 PM pass validates whether targets hit.

Usage:
  python daily_main.py                          # run the daily scan (writes DB)
  python daily_main.py --validate               # run the 4 PM target-hit validation
  python daily_main.py --universe sp500 --top 10
  python daily_main.py --no-db                  # scan without persisting
  python daily_main.py --validate --date 2026-08-03
"""
import argparse
import json
import sys
from datetime import date

from utils.logger import setup_logging


def main() -> None:
    p = argparse.ArgumentParser(description="Daily conviction + Fibonacci scanner")
    p.add_argument("--validate", action="store_true",
                   help="Run the 4 PM whole-day target-hit validation instead of a scan")
    p.add_argument("--universe", default=None,
                   help="Universe key (default: config.DEFAULT_UNIVERSE)")
    p.add_argument("--top", type=int, default=10,
                   help="Number of longs and shorts to keep (default: 10)")
    p.add_argument("--no-db", action="store_true",
                   help="Do not write results to the database")
    p.add_argument("--date", default=None,
                   help="Validation date YYYY-MM-DD (default: today ET)")
    args = p.parse_args()

    setup_logging()

    if args.validate:
        from daily.validate import validate_daily_targets
        td = date.fromisoformat(args.date) if args.date else None
        result = validate_daily_targets(trade_date=td)
    else:
        from daily.scanner import run_daily_scan
        result = run_daily_scan(universe=args.universe, top_n=args.top,
                                write_db=not args.no_db)

    print(json.dumps(result, indent=2, default=str))
    sys.exit(0 if result.get("status") == "ok" else 1)


if __name__ == "__main__":
    main()
