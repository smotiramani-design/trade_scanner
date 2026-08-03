"""
daily/ — the once-a-day scanner.

Formerly a separate project (MomentumStockScreener). It now lives inside
trade_scanner and reuses the same engine as the intraday scanner: the 10 signals
(+ market sentiment) conviction model and the Fibonacci projection module, run on
DAILY bars.

Pipeline:
  09:15 ET  daily/scanner.run_daily_scan()      → top 10 long + top 10 short,
                                                   each with a whole-day Fib target,
                                                   persisted to momentum_scans/picks
  16:00 ET  daily/validate.validate_daily_targets() → mark each target hit / missed

Entry points for CLI and AWS Lambda live in daily/run.py.
"""
