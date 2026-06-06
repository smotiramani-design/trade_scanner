"""
utils/spreadsheet.py — builds a formatted Excel workbook (.xlsx) from scan results.

Sheets:
  1. Top Picks        — top 5 bull + top 5 bear with full conviction details
  2. All Results      — every scanned ticker sorted by net score
  3. Signal Detail    — per-signal breakdown for every ticker
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import openpyxl
from openpyxl.styles import (
    Alignment, Border, Font, PatternFill, Side, numbers
)
from openpyxl.utils import get_column_letter

import config
from signals.base import TickerAnalysis
from signals.conviction import ConvictionScore

log = logging.getLogger(__name__)

# ── Color palette ─────────────────────────────────────────────────────────────
BULL_DARK   = "1D6F42"
BULL_MID    = "2D9E5F"
BULL_LIGHT  = "C6EFCE"
BEAR_DARK   = "9C0006"
BEAR_MID    = "C82333"
BEAR_LIGHT  = "FFC7CE"
NEUTRAL_BG  = "F2F2F2"
HEADER_BG   = "1F3864"
HEADER_FG   = "FFFFFF"
ACCENT_BG   = "2E75B6"
ACCENT_FG   = "FFFFFF"
BORDER_CLR  = "BFBFBF"

SIG_NAMES = ["Candle", "Volume", "SMA", "Gaps", "Stoch", "CCI", "RR"]


def _thin_border() -> Border:
    s = Side(style="thin", color=BORDER_CLR)
    return Border(left=s, right=s, top=s, bottom=s)


def _fill(hex_color: str) -> PatternFill:
    return PatternFill("solid", fgColor=hex_color)


def _header_font(bold: bool = True, color: str = HEADER_FG, size: int = 10) -> Font:
    return Font(name="Calibri", bold=bold, color=color, size=size)


def _body_font(bold: bool = False, color: str = "000000", size: int = 10) -> Font:
    return Font(name="Calibri", bold=bold, color=color, size=size)


def _write_header_row(ws, row: int, cols: List[str], fill_color: str = HEADER_BG) -> None:
    for c, label in enumerate(cols, 1):
        cell = ws.cell(row=row, column=c, value=label)
        cell.font      = _header_font()
        cell.fill      = _fill(fill_color)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border    = _thin_border()


def _bias_fill(bias_str: str) -> PatternFill:
    if bias_str == "bull":    return _fill(BULL_LIGHT)
    if bias_str == "bear":    return _fill(BEAR_LIGHT)
    return _fill(NEUTRAL_BG)


def _score_fill(score: int) -> PatternFill:
    if score >= 4:  return _fill(BULL_LIGHT)
    if score >= 2:  return _fill("E2EFDA")
    if score <= -4: return _fill(BEAR_LIGHT)
    if score <= -2: return _fill("FCE4D6")
    return _fill(NEUTRAL_BG)


def _set_col_widths(ws, widths: dict) -> None:
    for col_letter, w in widths.items():
        ws.column_dimensions[col_letter].width = w


# ── Sheet 1: Top Picks ────────────────────────────────────────────────────────

def _sheet_top_picks(wb, bulls: List[Tuple], bears: List[Tuple], universe: str, ts: str) -> None:
    ws = wb.active
    ws.title = "Top Picks"
    ws.sheet_view.showGridLines = False

    # Title
    ws.merge_cells("A1:L1")
    t = ws["A1"]
    t.value     = f"Trading Signal Scanner — Top Picks  |  Universe: {universe.upper()}  |  {ts}"
    t.font      = Font(name="Calibri", bold=True, size=13, color=HEADER_FG)
    t.fill      = _fill(HEADER_BG)
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 24

    row = 3
    for section_label, section_fill, picks in [
        ("▲  TOP 5 BULLISH — Highest Conviction Buys", BULL_DARK, bulls),
        ("▼  TOP 5 BEARISH — Highest Conviction Shorts / Avoids", BEAR_DARK, bears),
    ]:
        ws.merge_cells(f"A{row}:L{row}")
        c = ws.cell(row=row, column=1, value=section_label)
        c.font      = Font(name="Calibri", bold=True, size=11, color="FFFFFF")
        c.fill      = _fill(section_fill)
        c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        ws.row_dimensions[row].height = 20
        row += 1

        cols = ["Rank", "Ticker", "Price", "Chg %", "Score", "Bull", "Bear",
                "Grade", "Conviction %", "Verdict", "Key Signals", "Analysis"]
        _write_header_row(ws, row, cols, ACCENT_BG)
        ws.row_dimensions[row].height = 30
        row += 1

        for rank, (ta, cs) in enumerate(picks, 1):
            key_str  = " | ".join(cs.key_signals[:3])
            row_data = [
                rank,
                ta.ticker,
                f"${ta.price:.2f}" if ta.price else "—",
                f"{ta.chg_pct:+.2f}%" if ta.chg_pct else "—",
                f"{ta.net_score:+d}",
                ta.bull_count,
                ta.bear_count,
                cs.grade,
                f"{cs.conviction_pct:.1f}%",
                ta.verdict,
                key_str,
                cs.analysis,
            ]
            sfill = _fill(BULL_LIGHT) if cs.direction == "bullish" else _fill(BEAR_LIGHT)
            for c_idx, val in enumerate(row_data, 1):
                cell = ws.cell(row=row, column=c_idx, value=val)
                cell.font      = _body_font(bold=(c_idx == 2))
                cell.fill      = sfill
                cell.border    = _thin_border()
                cell.alignment = Alignment(
                    vertical="top", wrap_text=(c_idx == 12),
                    horizontal="center" if c_idx in (1,4,5,6,7,8,9) else "left"
                )
            ws.row_dimensions[row].height = 70 if len(cs.analysis) > 200 else 50
            row += 1
        row += 2

    _set_col_widths(ws, {
        "A": 6, "B": 9, "C": 10, "D": 9, "E": 8,
        "F": 6, "G": 6, "H": 8, "I": 12, "J": 18,
        "K": 36, "L": 72,
    })
    ws.freeze_panes = "A3"


# ── Sheet 2: All Results ──────────────────────────────────────────────────────

def _sheet_all_results(wb, results: List[TickerAnalysis], universe: str, ts: str) -> None:
    ws = wb.create_sheet("All Results")
    ws.sheet_view.showGridLines = False

    ws.merge_cells("A1:N1")
    t = ws["A1"]
    t.value     = f"All Scanned Tickers — {universe.upper()} — {ts}  ({len(results)} tickers)"
    t.font      = Font(name="Calibri", bold=True, size=12, color=HEADER_FG)
    t.fill      = _fill(HEADER_BG)
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 22

    cols = ["Ticker", "Price", "Chg %", "Net Score", "Bull", "Bear",
            "Verdict", "Bars", "Mode"] + SIG_NAMES
    _write_header_row(ws, 2, cols)
    ws.row_dimensions[2].height = 28
    ws.freeze_panes = "A3"

    for i, ta in enumerate(results, 3):
        row_vals = [
            ta.ticker,
            round(ta.price, 2) if ta.price else None,
            round(ta.chg_pct, 2) if ta.chg_pct else None,
            ta.net_score,
            ta.bull_count,
            ta.bear_count,
            ta.verdict,
            ta.bars,
            ta.mode,
        ] + [s.bias.value for s in ta.signals]

        for c_idx, val in enumerate(row_vals, 1):
            cell = ws.cell(row=i, column=c_idx, value=val)
            cell.font      = _body_font(bold=(c_idx == 1))
            cell.border    = _thin_border()
            cell.alignment = Alignment(
                horizontal="center" if c_idx != 1 else "left",
                vertical="center"
            )
            # score coloring
            if c_idx == 4:
                cell.fill = _score_fill(ta.net_score)
            elif c_idx >= 10:
                cell.fill = _bias_fill(str(val))
            elif i % 2 == 0:
                cell.fill = _fill("F9F9F9")

        # % format
        ws.cell(row=i, column=3).number_format = '+0.00%;-0.00%'

    _set_col_widths(ws, {
        "A": 9,  "B": 10, "C": 10, "D": 10, "E": 7,
        "F": 7,  "G": 20, "H": 8,  "I": 9,
        "J": 9,  "K": 9,  "L": 9,  "M": 9,
        "N": 9,  "O": 9,  "P": 9,
    })


# ── Sheet 3: Signal Detail ────────────────────────────────────────────────────

def _sheet_signal_detail(wb, results: List[TickerAnalysis]) -> None:
    ws = wb.create_sheet("Signal Detail")
    ws.sheet_view.showGridLines = False

    header = ["Ticker", "Price", "Score"]
    for n in SIG_NAMES:
        header += [n, f"{n} label"]
    _write_header_row(ws, 1, header)
    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "A2"

    for i, ta in enumerate(results, 2):
        row_vals = [ta.ticker, round(ta.price, 2) if ta.price else None, ta.net_score]
        for s in ta.signals:
            row_vals += [s.bias.value, s.label]
        for c_idx, val in enumerate(row_vals, 1):
            cell = ws.cell(row=i, column=c_idx, value=val)
            cell.font      = _body_font()
            cell.border    = _thin_border()
            cell.alignment = Alignment(horizontal="left", vertical="center")
            if c_idx == 3:
                cell.fill = _score_fill(ta.net_score)
            elif c_idx >= 4 and (c_idx - 4) % 2 == 0:
                col_sig_idx = (c_idx - 4) // 2
                if col_sig_idx < len(ta.signals):
                    cell.fill = _bias_fill(ta.signals[col_sig_idx].bias.value)

    ws.column_dimensions["A"].width = 9
    ws.column_dimensions["B"].width = 10
    ws.column_dimensions["C"].width = 8
    for i in range(4, 4 + len(SIG_NAMES) * 2, 2):
        ws.column_dimensions[get_column_letter(i)].width     = 9
        ws.column_dimensions[get_column_letter(i + 1)].width = 28


# ── Public entry point ────────────────────────────────────────────────────────

def build_spreadsheet(
    results:  List[TickerAnalysis],
    bulls:    List[Tuple],
    bears:    List[Tuple],
    universe: str,
    tag:      str = "",
) -> Path:
    """Build and save the full Excel workbook. Returns the file path."""
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M")
    stem = f"scan_{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    path = config.OUTPUT_DIR / f"{stem}.xlsx"

    wb = openpyxl.Workbook()
    _sheet_top_picks(wb, bulls, bears, universe, ts)
    _sheet_all_results(wb, results, universe, ts)
    _sheet_signal_detail(wb, results)

    wb.save(path)
    log.info("Spreadsheet saved → %s", path)
    return path
