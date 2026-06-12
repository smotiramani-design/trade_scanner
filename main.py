"""
main.py — Trading Signal Scanner CLI

Pipeline:
  1. Scan full universe (S&P 500 / Nasdaq 100 / Dow Jones / custom)
  2. Score all tickers by 7-signal conviction model
  3. Compute Fibonacci retracements + extensions synced to momentum
  4. Display top 5 bullish + bearish in Rich terminal tables
  5. Build Excel workbook (4 sheets: Top Picks, All Results, Signal Detail, Fibonacci)
  6. Send rich HTML email with Fibonacci section + spreadsheet attached

Usage:
  python main.py                                  # full S&P 500
  python main.py                                  # full major_us_markets (default)
  python main.py --universe major_us_markets      # 300 tickers: S&P500 + Nasdaq100 + DJ + NYSE
  python main.py --universe sp500 --max 50
  python main.py --universe nasdaq100
  python main.py --universe nyse
  python main.py --tickers AAPL,MSFT,NVDA,TSLA
  python main.py --universe sp500 --no-email
  python main.py --universe major_us_markets --daily
  python main.py --universe sp500 --show-all
"""
import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.progress import (Progress, SpinnerColumn, TextColumn,
                            BarColumn, TaskProgressColumn, TimeElapsedColumn)
from rich import box

import config
from utils.holidays import is_market_holiday
from trading import run_trade_session, get_client
from trading.position_monitor import run_position_monitor
from trading.pnl_tracker import get_performance_summary, format_summary_terminal
from utils import setup_logging, save_results, build_spreadsheet, send_email
from scanner import resolve_universe, scan
from signals.base import Bias, TickerAnalysis
from signals.conviction import ConvictionScore, score_conviction, top_picks

console = Console()
from signals import SIG_NAMES  # 10 signals — auto-updates when signals added
log = logging.getLogger(__name__)


# ── Rich helpers ──────────────────────────────────────────────────────────────

def _score_style(score: int) -> str:
    if score >= 4:  return "bold green"
    if score >= 2:  return "green"
    if score <= -4: return "bold red"
    if score <= -2: return "red"
    return "dim"


def _grade_style(grade: str) -> str:
    return {"A+": "bold green", "A": "green", "B": "yellow", "C": "yellow", "D": "dim"}.get(grade, "dim")


def _conviction_bar(pct: float, direction: str, width: int = 12) -> Text:
    filled = int(pct / 100 * width)
    bar    = "█" * filled + "░" * (width - filled)
    color  = "green" if direction == "bullish" else "red" if direction == "bearish" else "dim"
    return Text(f"{bar} {pct:.0f}%", style=color)


def build_top5_table(picks: List[Tuple[TickerAnalysis, ConvictionScore]],
                     direction: str, title: str) -> Table:
    accent = "green" if direction == "bullish" else "red"
    tbl = Table(title=title, box=box.ROUNDED, header_style=f"bold {accent}",
                show_lines=True, title_style=f"bold {accent}", expand=True)
    tbl.add_column("Rank",       justify="center", width=5)
    tbl.add_column("Ticker",     style="bold",     width=8)
    tbl.add_column("Company",                      width=22)
    tbl.add_column("Price",      justify="right",  width=9)
    tbl.add_column("Chg %",      justify="right",  width=8)
    tbl.add_column("Score",      justify="center", width=7)
    tbl.add_column("Grade",      justify="center", width=6)
    tbl.add_column("Conviction", width=18)
    tbl.add_column("Fib Target", justify="right",  width=12)
    tbl.add_column("Fib Label",  width=10)
    tbl.add_column("Signals",    width=14)
    tbl.add_column("Verdict",    width=20)

    for rank, (ta, cs) in enumerate(picks, 1):
        sig_text = Text()
        for s in ta.signals:
            m = {Bias.BULL: ("▲", "green"), Bias.BEAR: ("▼", "red"), Bias.NEUTRAL: ("—", "dim")}
            ch, col = m[s.bias]
            sig_text.append(ch, style=col)

        price_s = f"${ta.price:.2f}" if ta.price else "—"
        chg_s   = f"{ta.chg_pct:+.2f}%" if ta.chg_pct else "—"
        chg_col = "green" if (ta.chg_pct or 0) >= 0 else "red"

        fib_target = "—"
        fib_label  = ""
        if ta.fib and ta.fib.next_hour_target:
            fib_target = f"${ta.fib.next_hour_target:.2f}"
            fib_label  = ta.fib.next_hour_label
            fib_col    = "green" if ta.fib.direction == "bullish" else "red"
        else:
            fib_col = "dim"

        tbl.add_row(
            str(rank), ta.ticker,
            Text(ta.company_name[:20] + "…" if len(ta.company_name) > 20 else ta.company_name,
                 style="dim"),
            price_s,
            Text(chg_s,                       style=chg_col),
            Text(f"{ta.net_score:+d}",         style=_score_style(ta.net_score)),
            Text(cs.grade,                     style=_grade_style(cs.grade)),
            _conviction_bar(cs.conviction_pct, direction),
            Text(fib_target,                   style=fib_col),
            Text(fib_label,                    style="dim"),
            sig_text,
            Text(ta.verdict,                   style=_score_style(ta.net_score)),
        )
    return tbl


def build_full_table(results: List[TickerAnalysis], limit: int = 30) -> Table:
    tbl = Table(
        title=f"All Results — {min(limit, len(results))} of {len(results)}",
        box=box.SIMPLE_HEAVY, header_style="bold blue", show_lines=False, expand=True,
    )
    tbl.add_column("Ticker",     style="bold",    width=8)
    tbl.add_column("Price",      justify="right", width=9)
    tbl.add_column("Chg %",      justify="right", width=8)
    tbl.add_column("Score",      justify="center",width=7)
    tbl.add_column("Bull/Bear",  justify="center",width=9)
    tbl.add_column("Signals",    width=14)
    tbl.add_column("Fib Target", justify="right", width=12)
    tbl.add_column("Verdict",    width=20)

    for ta in results[:limit]:
        sig_text = Text()
        for s in ta.signals:
            m = {Bias.BULL: ("▲", "green"), Bias.BEAR: ("▼", "red"), Bias.NEUTRAL: ("—", "dim")}
            ch, col = m[s.bias]
            sig_text.append(ch, style=col)

        price_s    = f"${ta.price:.2f}" if ta.price else "—"
        chg_s      = f"{ta.chg_pct:+.2f}%" if ta.chg_pct else "—"
        chg_col    = "green" if (ta.chg_pct or 0) >= 0 else "red"
        bull_bear  = f"{ta.bull_count}B/{ta.bear_count}S"

        fib_s = "—"
        fib_c = "dim"
        if ta.fib and ta.fib.next_hour_target:
            fib_s = f"${ta.fib.next_hour_target:.2f} ({ta.fib.next_hour_label})"
            fib_c = "green" if ta.fib.direction == "bullish" else "red"

        tbl.add_row(
            ta.ticker, price_s,
            Text(chg_s,        style=chg_col),
            Text(f"{ta.net_score:+d}", style=_score_style(ta.net_score)),
            bull_bear, sig_text,
            Text(fib_s,        style=fib_c),
            Text(ta.verdict,   style=_score_style(ta.net_score)),
        )
    return tbl


def print_conviction_detail(ta: TickerAnalysis, cs: ConvictionScore,
                             rank: int, direction: str) -> None:
    accent = "green" if direction == "bullish" else "red"
    lines  = Text()
    lines.append(f"  Conviction : ", style="dim")
    lines.append(f"{cs.conviction_pct:.1f}%  Grade: {cs.grade}\n", style=f"bold {accent}")
    lines.append(f"  Analysis   : ", style="dim")
    lines.append(cs.analysis + "\n", style="white")
    if cs.key_signals:
        lines.append(f"  Key signals: ", style="dim")
        lines.append(", ".join(cs.key_signals[:3]) + "\n", style=accent)
    if cs.conflicting:
        lines.append(f"  ⚠ Conflicts: ", style="yellow")
        lines.append(", ".join(cs.conflicting) + "\n", style="yellow")
    if ta.fib:
        fib = ta.fib
        lines.append(f"\n  📐 Fibonacci ({fib.anchor_type})\n", style="bold cyan")
        lines.append(f"  Anchor     : ${fib.swing_low:.2f} – ${fib.swing_high:.2f} (range ${fib.swing_range:.2f})\n", style="dim")
        if fib.next_hour_target:
            lines.append(f"  Next target: ", style="dim")
            lines.append(f"${fib.next_hour_target:.2f} ({fib.next_hour_label})\n", style=f"bold {accent}")
        if fib.support_1:
            lines.append(f"  Support 1  : ", style="dim")
            lines.append(f"${fib.support_1:.2f}\n", style="green")
        if fib.resistance_1:
            lines.append(f"  Resistance : ", style="dim")
            lines.append(f"${fib.resistance_1:.2f}\n", style="red")
        lines.append(f"  Retracements: ", style="dim")
        lines.append("  ".join(f"{l.label}=${l.price:.2f}" for l in fib.retracements) + "\n", style="blue")
        lines.append(f"  Extensions  : ", style="dim")
        lines.append("  ".join(f"{l.label}=${l.price:.2f}" for l in fib.extensions[:4]) + "\n", style=accent)

    console.print(Panel(
        lines,
        title=f"[bold {accent}]#{rank} {ta.ticker}[/] — {ta.verdict}",
        border_style=accent, expand=False,
    ))


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.command()
@click.option("--universe", "-u", default=None,
              type=click.Choice(["major_us_markets", "sp500", "nasdaq100", "dowjones", "nyse_american", "watchlist", "watchlist_t1", "watchlist_t2"], case_sensitive=False))
@click.option("--tickers", "-t", default=None, help="Comma-separated custom tickers.")
@click.option("--max", "max_tickers", default=None, type=int, help="Cap tickers scanned.")
@click.option("--top", "top_n", default=None, type=int, help="Top N conviction picks.")
@click.option("--daily",  is_flag=True, default=False, help="Force daily chart mode.")
@click.option("--hourly", is_flag=True, default=False, help="Force hourly chart mode.")
@click.option("--no-email",  "skip_email", is_flag=True, default=False)
@click.option("--no-save",   "skip_save",  is_flag=True, default=False)
@click.option("--no-trade",  "skip_trade", is_flag=True, default=False,
              help="Skip Alpaca trade execution.")
@click.option("--dry-run",   "dry_run",    is_flag=True, default=False,
              help="Evaluate trades but do not submit orders.")
@click.option("--show-all",  is_flag=True, default=False, help="Print full results table.")
def cli(universe, tickers, max_tickers, top_n, daily, hourly,
        skip_email, skip_save, show_all, skip_trade, dry_run):

    setup_logging()
    n = top_n or config.TOP_N_PICKS

    if not universe and not tickers:
        universe = config.DEFAULT_UNIVERSE

    if tickers:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        tag = "custom"
    else:
        mx = max_tickers or config.MAX_TICKERS
        ticker_list = resolve_universe(universe, mx)
        tag = universe

    if not ticker_list:
        console.print("[red]No tickers resolved.[/]")
        sys.exit(1)

    market_open: Optional[bool] = None
    if daily:  market_open = False
    if hourly: market_open = True

    # Determine scan session for email subject/labels
    from data.fmp_client import get_market_session, MarketSession
    _ms = get_market_session()
    if   daily:  scan_session = "closed"
    elif hourly: scan_session = "open"
    else:
        scan_session = {
            MarketSession.PREMARKET:  "premarket",
            MarketSession.OPEN:       "open",
            MarketSession.AFTERHOURS: "afterhours",
            MarketSession.CLOSED:     "closed",
        }.get(_ms, "closed")

    ts_label = datetime.now().strftime("%Y-%m-%d %H:%M")
    console.rule(f"[bold]Trading Signal Scanner[/] — {universe or 'custom'} — {ts_label}")

    # ── Market holiday guard ───────────────────────────────────────────────────
    if is_market_holiday() and not tickers:
        console.print("[yellow]🏛[/] Today is a NYSE market holiday — scan skipped.")
        console.print("[dim]Use --tickers to force a scan on specific symbols.[/]")
        sys.exit(0)
    trade_status = (
        "disabled (--no-trade)" if skip_trade else
        "dry-run" if dry_run else
        "enabled (PAPER)" if (config.TRADE_ENABLED and config.ALPACA_PAPER) else
        "disabled (TRADE_ENABLED=false)" if not config.TRADE_ENABLED else
        "⚠ LIVE" if not config.ALPACA_PAPER else
        "not configured"
    )
    console.print(
        f"[dim]Tickers: {len(ticker_list)}  ·  Top picks: {n}  ·  "
        f"Email: {'skip' if skip_email else 'enabled' if config.EMAIL_ENABLED else 'not configured'}  ·  "
        f"Trading: {trade_status}[/]\n"
    )

    # ── Scan ──────────────────────────────────────────────────────────────────
    results: List[TickerAnalysis] = []
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  BarColumn(), TaskProgressColumn(), TimeElapsedColumn(),
                  console=console, transient=True) as prog:
        task = prog.add_task("Scanning…", total=len(ticker_list))
        def cb(done, total, ticker):
            prog.update(task, advance=1, description=f"[cyan]{ticker}[/cyan]")
        results = scan(ticker_list, market_open=market_open, progress_cb=cb)

    if not results:
        console.print("[red]No results. Check FMP API key and ticker list.[/]")
        sys.exit(1)

    mode_label = "Hourly · 3-month" if results[0].mode == "Hourly" else "Daily · 1-year"
    console.print(f"[green]✓[/] {len(results)} tickers analyzed  [{mode_label}]")

    # ── Conviction + top picks ────────────────────────────────────────────────
    bulls, bears = top_picks(results, n)

    # ── Terminal display ──────────────────────────────────────────────────────
    console.print()
    console.print(build_top5_table(bulls, "bullish", f"▲  Top {n} Bullish Conviction Picks"))
    console.print()
    for rank, (ta, cs) in enumerate(bulls, 1):
        print_conviction_detail(ta, cs, rank, "bullish")

    console.print()
    console.print(build_top5_table(bears, "bearish", f"▼  Top {n} Bearish Conviction Picks"))
    console.print()
    for rank, (ta, cs) in enumerate(bears, 1):
        print_conviction_detail(ta, cs, rank, "bearish")

    if show_all:
        console.print()
        console.print(build_full_table(results, limit=len(results)))

    strong_bull = sum(1 for r in results if r.net_score >= 4)
    strong_bear = sum(1 for r in results if r.net_score <= -4)
    neutral     = sum(1 for r in results if -1 <= r.net_score <= 1)
    console.print(
        f"\n[dim]Summary — Strong bull: [green]{strong_bull}[/]  "
        f"Strong bear: [red]{strong_bear}[/]  "
        f"Neutral: {neutral}  Total: {len(results)}[/]"
    )

    # ── Save spreadsheet ──────────────────────────────────────────────────────
    xlsx_path: Optional[Path] = None
    if not skip_save:
        try:
            xlsx_path = build_spreadsheet(results, bulls, bears, universe or "custom", tag)
            console.print(f"[green]✓[/] Spreadsheet → [bold]{xlsx_path.name}[/]")
            save_results(results, tag=tag)
        except Exception as e:
            log.error("Spreadsheet save failed: %s", e)
            console.print(f"[yellow]⚠[/] Spreadsheet save failed: {e}")

    # ── Position monitor — check stops/TP on existing positions ─────────────
    monitor_actions = []
    if not skip_trade and config.ALPACA_ENABLED:
        monitor_actions = run_position_monitor(dry_run=(dry_run or not config.TRADE_ENABLED))
        closed_count  = sum(1 for a in monitor_actions if a.closed)
        holding_count = sum(1 for a in monitor_actions if a.action == "hold")
        stop_count    = sum(1 for a in monitor_actions if a.action == "close_stop")
        tp_count      = sum(1 for a in monitor_actions if a.action == "close_tp")
        if monitor_actions:
            console.print(
                f"\n[dim]Position monitor:[/] {holding_count} holding · "
                f"[red]{stop_count} stop[/] · [green]{tp_count} TP[/] closed"
            )
        # P&L summary
        ps = get_performance_summary()
        if ps.total_trades > 0:
            console.print()
            console.print(format_summary_terminal(ps))

    # ── Alpaca paper trading ─────────────────────────────────────────────────
    bull_decisions, bear_decisions, account_summary = [], [], None
    if not skip_trade:
        if not config.ALPACA_ENABLED:
            console.print("\n[yellow]⚠[/] Alpaca not configured — skipping trade execution. "
                          "Set ALPACA_API_KEY and ALPACA_SECRET_KEY in .env")
        else:
            console.print("\n[dim]Running Alpaca trade evaluation…[/]")
            effective_dry_run = dry_run or not config.TRADE_ENABLED
            bull_decisions, bear_decisions, account_summary = run_trade_session(
                bulls, bears, dry_run=effective_dry_run
            )
            executed = sum(1 for d in bull_decisions + bear_decisions if d.executed)
            skipped  = sum(1 for d in bull_decisions + bear_decisions if d.action == "skip")
            mode_label = "[yellow]DRY RUN[/]" if effective_dry_run else "[green]PAPER[/]"
            console.print(
                f"[green]✓[/] Trade session: {executed} executed · {skipped} skipped "
                f"[{mode_label}]"
            )
            if account_summary:
                console.print(
                    f"[dim]Account: equity=${account_summary['equity']:,.2f} · "
                    f"cash=${account_summary['cash']:,.2f} · "
                    f"buying power=${account_summary['buying_power']:,.2f}[/]"
                )

    n_sigs = len(SIG_NAMES)   # dynamic signal count (10 signals)
    # ── Email ─────────────────────────────────────────────────────────────────
    if not skip_email:
        console.print("\n[dim]Sending email…[/]")
        ok = send_email(
            bulls, bears, results, universe or "custom",
            attachment=xlsx_path,
            bull_decisions=bull_decisions,
            bear_decisions=bear_decisions,
            account_summary=account_summary,
            dry_run=(dry_run or not config.TRADE_ENABLED),
            scan_session=scan_session,
        )
        if ok:
            console.print(f"[green]✓[/] Email sent to: {', '.join(config.EMAIL_TO)}")
        else:
            console.print("[yellow]⚠[/] Email not sent — check .env SMTP settings.")

    console.rule("[dim]Done[/]")


if __name__ == "__main__":
    cli()
