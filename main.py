"""
main.py — Trading Signal Scanner CLI

Full pipeline:
  1. Scan full universe (S&P 500 / Nasdaq 100 / Dow Jones / custom)
  2. Score all tickers by 7-signal conviction model
  3. Display top 5 bullish + top 5 bearish in Rich terminal table
  4. Build formatted Excel workbook with all results + top picks
  5. Send rich HTML email with analysis commentary + spreadsheet attached
  6. Send SMS alert with top picks summary via Twilio

Usage:
  python main.py                                 # scan full S&P 500 (default)
  python main.py --universe nasdaq100            # full Nasdaq 100
  python main.py --universe sp500 --max 100      # cap at 100 tickers
  python main.py --tickers AAPL,MSFT,NVDA,TSLA  # custom list
  python main.py --universe sp500 --no-email     # skip email
  python main.py --universe sp500 --no-sms       # skip SMS
  python main.py --daily                         # force daily chart mode
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
from rich.columns import Columns
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich import box

import config
from utils import setup_logging, save_results, build_spreadsheet, send_email, send_sms
from scanner import resolve_universe, scan
from signals.base import Bias, TickerAnalysis
from signals.conviction import ConvictionScore, score_conviction, top_picks

console = Console()
SIG_NAMES = ["Candle", "Volume", "SMA", "Gaps", "Stoch", "CCI", "RR"]
log = logging.getLogger(__name__)


# ── Rich rendering helpers ────────────────────────────────────────────────────

def _bias_char(bias: Bias) -> Text:
    m = {Bias.BULL: ("▲", "green"), Bias.BEAR: ("▼", "red"), Bias.NEUTRAL: ("—", "dim")}
    ch, col = m[bias]
    return Text(ch, style=col)


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
    tbl = Table(
        title=title, box=box.ROUNDED,
        header_style=f"bold {accent}", show_lines=True,
        title_style=f"bold {accent}", expand=True,
    )
    tbl.add_column("Rank",       justify="center", width=5)
    tbl.add_column("Ticker",     style="bold",     width=8)
    tbl.add_column("Price",      justify="right",  width=9)
    tbl.add_column("Chg %",      justify="right",  width=8)
    tbl.add_column("Score",      justify="center", width=7)
    tbl.add_column("Grade",      justify="center", width=6)
    tbl.add_column("Conviction", width=18)
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

        tbl.add_row(
            str(rank),
            ta.ticker,
            price_s,
            Text(chg_s, style=chg_col),
            Text(f"{ta.net_score:+d}", style=_score_style(ta.net_score)),
            Text(cs.grade, style=_grade_style(cs.grade)),
            _conviction_bar(cs.conviction_pct, direction),
            sig_text,
            Text(ta.verdict, style=_score_style(ta.net_score)),
        )
    return tbl


def build_full_table(results: List[TickerAnalysis], limit: int = 30) -> Table:
    tbl = Table(
        title=f"All Results — Top {min(limit, len(results))} of {len(results)} tickers",
        box=box.SIMPLE_HEAVY, header_style="bold blue",
        show_lines=False, expand=True,
    )
    tbl.add_column("Ticker",  style="bold",    width=8)
    tbl.add_column("Price",   justify="right", width=9)
    tbl.add_column("Chg %",   justify="right", width=8)
    tbl.add_column("Score",   justify="center",width=7)
    tbl.add_column("Bull",    justify="center",width=5)
    tbl.add_column("Bear",    justify="center",width=5)
    tbl.add_column("Signals", width=14)
    tbl.add_column("Verdict", width=20)

    for ta in results[:limit]:
        sig_text = Text()
        for s in ta.signals:
            m = {Bias.BULL: ("▲", "green"), Bias.BEAR: ("▼", "red"), Bias.NEUTRAL: ("—", "dim")}
            ch, col = m[s.bias]
            sig_text.append(ch, style=col)

        price_s = f"${ta.price:.2f}" if ta.price else "—"
        chg_s   = f"{ta.chg_pct:+.2f}%" if ta.chg_pct else "—"
        chg_col = "green" if (ta.chg_pct or 0) >= 0 else "red"

        tbl.add_row(
            ta.ticker,
            price_s,
            Text(chg_s, style=chg_col),
            Text(f"{ta.net_score:+d}", style=_score_style(ta.net_score)),
            Text(str(ta.bull_count), style="green"),
            Text(str(ta.bear_count), style="red"),
            sig_text,
            Text(ta.verdict, style=_score_style(ta.net_score)),
        )
    return tbl


def print_conviction_detail(ta: TickerAnalysis, cs: ConvictionScore, rank: int,
                             direction: str) -> None:
    accent = "green" if direction == "bullish" else "red"
    lines  = Text()
    lines.append(f"  Conviction: ", style="dim")
    lines.append(f"{cs.conviction_pct:.1f}%  Grade: {cs.grade}\n", style=f"bold {accent}")
    lines.append(f"  Analysis:   ", style="dim")
    lines.append(cs.analysis + "\n", style="white")
    if cs.key_signals:
        lines.append(f"  Key signals: ", style="dim")
        lines.append(", ".join(cs.key_signals[:3]) + "\n", style=accent)
    if cs.conflicting:
        lines.append(f"  ⚠ Conflicts: ", style="yellow")
        lines.append(", ".join(cs.conflicting) + "\n", style="yellow")
    console.print(Panel(
        lines,
        title=f"[bold {accent}]#{rank} {ta.ticker}[/] — {ta.verdict}",
        border_style=accent,
        expand=False,
    ))


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.command()
@click.option("--universe", "-u", default=None,
              type=click.Choice(["sp500", "nasdaq100", "dowjones"], case_sensitive=False),
              help="Index universe to scan.")
@click.option("--tickers", "-t", default=None,
              help="Comma-separated custom tickers.")
@click.option("--max", "max_tickers", default=None, type=int,
              help="Cap number of tickers scanned.")
@click.option("--top", "top_n", default=None, type=int,
              help="Number of top conviction picks (default from .env TOP_N_PICKS).")
@click.option("--daily", is_flag=True, default=False,
              help="Force daily chart mode.")
@click.option("--hourly", is_flag=True, default=False,
              help="Force hourly chart mode.")
@click.option("--no-email", "skip_email", is_flag=True, default=False,
              help="Skip sending email.")
@click.option("--no-sms", "skip_sms", is_flag=True, default=False,
              help="Skip sending SMS.")
@click.option("--no-save", "skip_save", is_flag=True, default=False,
              help="Skip saving files.")
@click.option("--show-all", is_flag=True, default=False,
              help="Print full results table in terminal.")
def cli(universe, tickers, max_tickers, top_n, daily, hourly,
        skip_email, skip_sms, skip_save, show_all):
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

    ts_label = datetime.now().strftime("%Y-%m-%d %H:%M")
    console.rule(f"[bold]Trading Signal Scanner[/] — {universe or 'custom'} — {ts_label}")
    console.print(f"[dim]Tickers: {len(ticker_list)}  ·  Top picks: {n}  ·  "
                  f"Email: {'disabled' if skip_email else 'enabled' if config.EMAIL_ENABLED else 'not configured'}  ·  "
                  f"SMS: {'disabled' if skip_sms else 'enabled' if config.SMS_ENABLED else 'not configured'}[/]\n")

    # ── 1. Scan ───────────────────────────────────────────────────────────────
    results: List[TickerAnalysis] = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console, transient=True,
    ) as prog:
        task = prog.add_task("Scanning…", total=len(ticker_list))
        def cb(done, total, ticker):
            prog.update(task, advance=1, description=f"[cyan]{ticker}[/cyan]")
        results = scan(ticker_list, market_open=market_open, progress_cb=cb)

    if not results:
        console.print("[red]No results returned. Check your FMP API key and ticker list.[/]")
        sys.exit(1)

    mode_label = "Hourly · 3-month" if results[0].mode == "Hourly" else "Daily · 1-year"
    console.print(f"[green]✓[/] Scan complete — [bold]{len(results)}[/] tickers analyzed  [{mode_label}]")

    # ── 2. Conviction scoring + top picks ────────────────────────────────────
    bulls, bears = top_picks(results, n)

    # ── 3. Terminal display ───────────────────────────────────────────────────
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

    # ── Summary stats ─────────────────────────────────────────────────────────
    strong_bull = sum(1 for r in results if r.net_score >= 4)
    strong_bear = sum(1 for r in results if r.net_score <= -4)
    neutral     = sum(1 for r in results if -1 <= r.net_score <= 1)
    console.print()
    console.print(
        f"[dim]Universe summary — "
        f"Strong bull: [green]{strong_bull}[/]  "
        f"Strong bear: [red]{strong_bear}[/]  "
        f"Neutral: {neutral}  "
        f"Total: {len(results)}[/]"
    )

    # ── 4. Save spreadsheet ──────────────────────────────────────────────────
    xlsx_path: Optional[Path] = None
    if not skip_save:
        try:
            xlsx_path = build_spreadsheet(results, bulls, bears, universe or "custom", tag)
            console.print(f"[green]✓[/] Spreadsheet saved → [bold]{xlsx_path.name}[/]")
            save_results(results, tag=tag)
        except Exception as e:
            log.error("Failed to save spreadsheet: %s", e)
            console.print(f"[yellow]⚠[/] Spreadsheet save failed: {e}")

    # ── 5. Email ─────────────────────────────────────────────────────────────
    if not skip_email:
        console.print("\n[dim]Sending email…[/]")
        ok = send_email(bulls, bears, results, universe or "custom", attachment=xlsx_path)
        if ok:
            console.print(f"[green]✓[/] Email sent to: {', '.join(config.EMAIL_TO)}")
        else:
            console.print("[yellow]⚠[/] Email not sent. Check .env SMTP settings.")

    # ── 6. SMS ───────────────────────────────────────────────────────────────
    if not skip_sms:
        console.print("[dim]Sending SMS…[/]")
        ok = send_sms(bulls, bears, universe or "custom", len(results))
        if ok:
            console.print(f"[green]✓[/] SMS sent to: {', '.join(config.SMS_TO_NUMBERS)}")
        else:
            console.print("[yellow]⚠[/] SMS not sent. Check .env Twilio settings.")

    console.rule("[dim]Done[/]")


if __name__ == "__main__":
    cli()
