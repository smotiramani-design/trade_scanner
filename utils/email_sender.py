"""
utils/email_sender.py — rich HTML email with:
  • Top 5 bullish + bearish conviction picks with commentary
  • Fibonacci price projections section (retracements + extensions)
  • Full scan summary table
  • Spreadsheet attached
"""
from __future__ import annotations

import logging
import smtplib
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Optional, Tuple

import config
from signals.base import TickerAnalysis
from utils.sector_heatmap import build_heatmap_html
from signals.conviction import ConvictionScore
from signals.fibonacci import FibLevels

log = logging.getLogger(__name__)
from signals import SIG_NAMES as _SIG_FULL
SIG_NAMES = [s.split(".")[0].split(" ")[0][:6] for s in _SIG_FULL]


# ── HTML helpers ──────────────────────────────────────────────────────────────

def _bias_dot(bias: str) -> str:
    colors = {"bull": "#1D9E75", "bear": "#D85A30", "neutral": "#888"}
    icons  = {"bull": "▲", "bear": "▼", "neutral": "—"}
    return f'<span style="color:{colors.get(bias,"#888")};font-weight:700">{icons.get(bias,"—")}</span>'


def _grade_badge(grade: str) -> str:
    colors = {
        "A+": ("#FFFFFF", "#1D6F42"), "A": ("#FFFFFF", "#2D9E5F"),
        "B":  ("#27500A", "#C6EFCE"), "C": ("#633806", "#FAEEDA"),
        "D":  ("#888888", "#F2F2F2"),
    }
    fg, bg = colors.get(grade, ("#000", "#eee"))
    return (f'<span style="background:{bg};color:{fg};padding:2px 8px;'
            f'border-radius:4px;font-weight:700;font-size:12px">{grade}</span>')


def _conviction_bar(pct: float, direction: str) -> str:
    color = "#1D9E75" if direction == "bullish" else "#D85A30" if direction == "bearish" else "#888"
    w = min(int(pct), 100)
    return (f'<div style="background:#eee;border-radius:3px;height:8px;width:120px;'
            f'display:inline-block;vertical-align:middle">'
            f'<div style="background:{color};width:{w}%;height:100%;border-radius:3px"></div>'
            f'</div> <span style="font-size:12px;color:{color};font-weight:600">{pct:.0f}%</span>')


def _signal_chips(ta: TickerAnalysis) -> str:
    chips = []
    for i, sig in enumerate(ta.signals):
        name = SIG_NAMES[i] if i < len(SIG_NAMES) else ""
        c  = {"bull": "#C6EFCE", "bear": "#FFC7CE", "neutral": "#F2F2F2"}.get(sig.bias.value, "#eee")
        tc = {"bull": "#1D6F42", "bear": "#9C0006", "neutral": "#666"}.get(sig.bias.value, "#333")
        chips.append(
            f'<span style="background:{c};color:{tc};border-radius:4px;'
            f'padding:2px 6px;font-size:11px;margin:2px;display:inline-block">'
            f'{_bias_dot(sig.bias.value)} {name}</span>'
        )
    return "".join(chips)


# ── Fibonacci HTML section ────────────────────────────────────────────────────

def _greeks_badge(ta) -> str:
    """Render a compact Greeks/gamma badge for the pick card. Empty string if no data."""
    gd = getattr(ta, "gamma_data", None)
    if not gd or not gd.nearest_strike:
        return ""
    if gd.pin_risk:
        bg, color, icon = "#FFF3CD", "#856404", "⚡ Gamma Pin"
        note = f"${gd.nearest_strike:.2f} strike — size reduced to 75%"
    elif gd.squeeze_setup:
        bg, color, icon = "#E8F5E9", "#1D6F42", "🚀 Gamma Squeeze"
        note = f"Breaking ${gd.nearest_strike:.2f} strike — size increased to 125%"
    else:
        bg, color, icon = "#F0F4FF", "#2E75B6", "Γ Options"
        note = gd.detail[:70] if gd.detail else f"Nearest: ${gd.nearest_strike:.2f}"
    return f'''<div style="margin-top:8px;font-size:12px;color:{color};background:{bg};
  padding:6px 10px;border-radius:4px;border-left:3px solid {color}">
  <strong>{icon}</strong> &nbsp; {note}
  {f'&nbsp;·&nbsp; γ={gd.nearest_gamma:.4f} OI={gd.nearest_oi:,}' if gd.nearest_gamma else ''}
</div>'''


def _fib_table(fib: FibLevels, direction: str) -> str:
    """Render a compact entry/stop/target table for one pick card."""
    if not fib:
        return ""

    accent   = "#1D6F42" if direction == "bullish" else "#9C0006" if direction == "bearish" else "#2E75B6"
    bg_light = "#F0FFF6" if direction == "bullish" else "#FFF5F5" if direction == "bearish" else "#F0F4FF"
    dir_arrow = "▲" if direction == "bullish" else "▼" if direction == "bearish" else "↔"

    def _price(v): return f"${v:.2f}" if v else "N/A"
    def _rr(v):    return f"{v:.1f}x" if v else "—"

    anchor_note = f"Anchor: {fib.anchor_type} &nbsp;·&nbsp; Swing ${fib.swing_low:.2f}–${fib.swing_high:.2f} (range ${fib.swing_range:.2f})"

    # Quality badge
    quality, q_bg, q_fg = "—", "#eee", "#666"
    if fib.risk_reward_t2:
        rr = fib.risk_reward_t2
        if rr >= 3.0:   quality, q_bg, q_fg = "A+ Setup", "#C6EFCE", "#1D6F42"
        elif rr >= 2.0: quality, q_bg, q_fg = "A Setup",  "#E8F5E9", "#2D9E5F"
        elif rr >= 1.5: quality, q_bg, q_fg = "B Setup",  "#FFF9C4", "#856404"
        else:           quality, q_bg, q_fg = "C Setup",  "#FCE4D6", "#9C0006"

    # Main entry/exit table rows
    rows = f"""
<tr>
  <td style="padding:6px 10px;font-weight:600;color:#2E75B6;background:#EEF4FF">Entry</td>
  <td style="padding:6px 10px;font-weight:600;background:#EEF4FF">{fib.entry_label}</td>
  <td style="padding:6px 10px;font-size:14px;font-weight:700;color:#2E75B6;background:#EEF4FF">{_price(fib.entry_price)}</td>
  <td style="padding:6px 10px;background:#EEF4FF;font-size:12px;color:#666">Ideal pullback entry level</td>
  <td style="padding:6px 10px;background:#EEF4FF"></td>
</tr>
<tr>
  <td style="padding:6px 10px;font-weight:600;color:#9C0006;background:#FFF5F5">Stop Loss</td>
  <td style="padding:6px 10px;font-weight:600;background:#FFF5F5">{fib.stop_label}</td>
  <td style="padding:6px 10px;font-size:14px;font-weight:700;color:#9C0006;background:#FFF5F5">{_price(fib.stop_loss)}</td>
  <td style="padding:6px 10px;background:#FFF5F5;font-size:12px;color:#666">Invalidation level — exit if breached</td>
  <td style="padding:6px 10px;background:#FFF5F5"></td>
</tr>
<tr>
  <td style="padding:6px 10px;font-weight:600;color:{accent};background:#FFFDE7">Target 1</td>
  <td style="padding:6px 10px;font-weight:600;background:#FFFDE7">{fib.target_1_label}</td>
  <td style="padding:6px 10px;font-size:14px;font-weight:700;color:{accent};background:#FFFDE7">{_price(fib.target_1)}</td>
  <td style="padding:6px 10px;background:#FFFDE7;font-size:12px;color:#666">First measured move — take partial profits</td>
  <td style="padding:6px 10px;background:#FFFDE7;font-weight:600;color:{accent}">{_rr(fib.risk_reward_t1)}</td>
</tr>
<tr>
  <td style="padding:6px 10px;font-weight:600;color:{accent}">Target 2</td>
  <td style="padding:6px 10px;font-weight:600">{fib.target_2_label}</td>
  <td style="padding:6px 10px;font-size:14px;font-weight:700;color:{accent}">{_price(fib.target_2)}</td>
  <td style="padding:6px 10px;font-size:12px;color:#666">Extended move — trail stop to entry</td>
  <td style="padding:6px 10px;font-weight:700;color:{accent}">{_rr(fib.risk_reward_t2)}</td>
</tr>
<tr>
  <td style="padding:6px 10px;font-weight:600;color:{accent}">Target 3</td>
  <td style="padding:6px 10px;font-weight:600">{fib.target_3_label}</td>
  <td style="padding:6px 10px;font-size:14px;font-weight:700;color:{accent}">{_price(fib.target_3)}</td>
  <td style="padding:6px 10px;font-size:12px;color:#666">Full measured move — maximum target</td>
  <td style="padding:6px 10px;font-weight:700;color:{accent}">{_rr(fib.risk_reward_t3)}</td>
</tr>
<tr style="background:#F4F4F4">
  <td colspan="2" style="padding:6px 10px;font-size:11px;color:#888">Next-hr momentum target</td>
  <td style="padding:6px 10px;font-weight:700;color:{accent}">{_price(fib.next_hour_target)} <span style="font-size:10px;color:#888">({fib.next_hour_label})</span></td>
  <td style="padding:6px 10px;font-size:11px;color:#888">Support: <strong style="color:#1D9E75">{_price(fib.support_1)}</strong> &nbsp; Resistance: <strong style="color:#D85A30">{_price(fib.resistance_1)}</strong></td>
  <td style="padding:6px 10px"></td>
</tr>"""

    return f"""
<div style="margin-top:12px;background:{bg_light};border-radius:6px;padding:12px 16px;
            border:1px solid {'#C6EFCE' if direction=='bullish' else '#FFC7CE' if direction=='bearish' else '#C9D8F0'}">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap">
    <span style="font-size:13px;font-weight:700;color:{accent}">
      📐 Fibonacci Trade Plan &nbsp;{dir_arrow}
    </span>
    <span style="background:{q_bg};color:{q_fg};padding:2px 8px;border-radius:4px;
                 font-size:11px;font-weight:700">{quality}</span>
    <span style="font-size:11px;color:#888;margin-left:auto">{anchor_note}</span>
  </div>
  <table width="100%" cellpadding="0" cellspacing="0"
         style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:13px;
                border:1px solid #ddd;border-radius:4px;overflow:hidden">
    <thead>
      <tr style="background:{accent};color:#fff">
        <th style="padding:7px 10px;text-align:left;width:90px">Level</th>
        <th style="padding:7px 10px;text-align:left;width:90px">Fib %</th>
        <th style="padding:7px 10px;text-align:left;width:90px">Price</th>
        <th style="padding:7px 10px;text-align:left">Notes</th>
        <th style="padding:7px 10px;text-align:left;width:60px">R/R</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""



# ── Pick card ─────────────────────────────────────────────────────────────────

def _pick_card(rank: int, ta: TickerAnalysis, cs: ConvictionScore, direction: str) -> str:
    accent  = "#1D6F42" if direction == "bullish" else "#9C0006"
    bg      = "#F0FFF6" if direction == "bullish" else "#FFF5F5"
    chg_c   = "#1D9E75" if (ta.chg_pct or 0) >= 0 else "#D85A30"
    chg_s   = f"{ta.chg_pct:+.2f}%" if ta.chg_pct else "—"
    price_s = f"${ta.price:.2f}" if ta.price else "—"
    fib_html     = _fib_table(ta.fib, direction) if ta.fib else ""
    greeks_badge = _greeks_badge(ta) if getattr(ta, "gamma_data", None) else ""

    return f"""
<div style="background:{bg};border-left:4px solid {accent};border-radius:6px;
            padding:16px 20px;margin-bottom:16px;font-family:Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td width="40">
        <div style="background:{accent};color:#fff;border-radius:50%;width:32px;height:32px;
                    text-align:center;line-height:32px;font-weight:700;font-size:14px">{rank}</div>
      </td>
      <td>
        <span style="font-size:22px;font-weight:700;color:{accent}">{ta.ticker}</span>
        {"" if not ta.company_name else f'<span style="font-size:13px;color:#666;margin-left:6px">{ta.company_name}</span>'}
        &nbsp;&nbsp;
        <span style="font-size:16px;color:#333;font-weight:600">{price_s}</span>
        &nbsp;
        <span style="font-size:14px;color:{chg_c};font-weight:600">{chg_s}</span>
      </td>
      <td align="right">
        {_grade_badge(cs.grade)}
        &nbsp;
        <span style="font-size:12px;color:#666">Score: <strong style="color:{accent}">{ta.net_score:+d}/{len(SIG_NAMES)}</strong></span>
      </td>
    </tr>
  </table>

  <div style="margin:10px 0 6px">
    {_conviction_bar(cs.conviction_pct, direction)}
    &nbsp;&nbsp;
    <span style="font-size:12px;color:#555;font-weight:600">{ta.verdict}</span>
  </div>

  <div style="margin:8px 0">{_signal_chips(ta)}</div>

  <div style="margin-top:10px;font-size:13px;color:#333;line-height:1.65;
              background:#fff;border-radius:4px;padding:10px 12px">
    {cs.analysis}
  </div>

  {"" if not cs.conflicting else
   f'<div style="margin-top:8px;font-size:12px;color:#856404;background:#FFF3CD;'
   f'padding:6px 10px;border-radius:4px">⚠ Conflicting signals: {", ".join(cs.conflicting)}</div>'}

  {fib_html}
  {greeks_badge}
</div>"""


# ── Summary table ─────────────────────────────────────────────────────────────

def _section_table(results: List[TickerAnalysis], title: str, limit: int = 30) -> str:
    rows_html = ""
    for i, ta in enumerate(results[:limit]):
        bg      = "#fff" if i % 2 == 0 else "#F9F9F9"
        sig_dots = "".join(_bias_dot(s.bias.value) for s in ta.signals)
        score_c  = "#1D9E75" if ta.net_score > 0 else "#D85A30" if ta.net_score < 0 else "#888"
        chg_c    = "#1D9E75" if (ta.chg_pct or 0) >= 0 else "#D85A30"
        price_s  = f"${ta.price:.2f}" if ta.price else "—"
        chg_s    = f"{ta.chg_pct:+.2f}%" if ta.chg_pct is not None else "—"
        score_s  = f"{ta.net_score:+d}/{len(SIG_NAMES)}"

        # Fib next target
        fib_target = ""
        fib_label  = ""
        if ta.fib and ta.fib.next_hour_target:
            fib_dir_arrow = "▲" if ta.fib.direction == "bullish" else "▼" if ta.fib.direction == "bearish" else "—"
            fib_dir_color = "#1D9E75" if ta.fib.direction == "bullish" else "#D85A30" if ta.fib.direction == "bearish" else "#888"
            fib_target = f'<span style="color:{fib_dir_color};font-weight:600">{fib_dir_arrow} ${ta.fib.next_hour_target:.2f}</span>'
            fib_label  = f'<span style="font-size:10px;color:#888">{ta.fib.next_hour_label}</span>'

        rows_html += f"""
<tr style="background:{bg}">
  <td style="padding:7px 10px;font-weight:700;font-size:13px">{ta.ticker}</td>
  <td style="padding:7px 10px;font-size:12px;color:#555;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{ta.company_name}</td>
  <td style="padding:7px 10px;text-align:right">{price_s}</td>
  <td style="padding:7px 10px;text-align:right;color:{chg_c}">{chg_s}</td>
  <td style="padding:7px 10px;text-align:center;color:{score_c};font-weight:700">{score_s}</td>
  <td style="padding:7px 10px;text-align:center">{ta.bull_count}</td>
  <td style="padding:7px 10px;text-align:center">{ta.bear_count}</td>
  <td style="padding:7px 10px;letter-spacing:3px">{sig_dots}</td>
  <td style="padding:7px 10px;font-size:12px;color:#555">{ta.verdict}</td>
  <td style="padding:7px 10px;text-align:center">{fib_target}<br>{fib_label}</td>
</tr>"""

    return f"""
<h3 style="font-family:Arial,sans-serif;color:#1F3864;margin:24px 0 8px">{title}</h3>
<table width="100%" cellpadding="0" cellspacing="0"
       style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:13px;
              border:1px solid #ddd;border-radius:6px;overflow:hidden">
  <thead>
    <tr style="background:#1F3864;color:#fff">
      <th style="padding:9px 10px;text-align:left">Ticker</th>
      <th style="padding:9px 10px;text-align:left">Company</th>
      <th style="padding:9px 10px;text-align:right">Price</th>
      <th style="padding:9px 10px;text-align:right">Chg %</th>
      <th style="padding:9px 10px;text-align:center">Score</th>
      <th style="padding:9px 10px;text-align:center">Bull</th>
      <th style="padding:9px 10px;text-align:center">Bear</th>
      <th style="padding:9px 10px">Signals</th>
      <th style="padding:9px 10px">Verdict</th>
      <th style="padding:9px 10px;text-align:center">Fib Target</th>
    </tr>
  </thead>
  <tbody>{rows_html}</tbody>
</table>"""



# ── Trade execution HTML section ──────────────────────────────────────────────

def _trade_summary_html(
    bull_decisions: list,
    bear_decisions: list,
    account: dict,
    dry_run: bool,
) -> str:
    if not bull_decisions and not bear_decisions:
        return ""

    mode_badge = (
        '<span style="background:#FFF3CD;color:#856404;padding:2px 8px;'
        'border-radius:4px;font-size:11px;font-weight:700">🧪 DRY RUN</span>'
        if dry_run else
        '<span style="background:#C6EFCE;color:#1D6F42;padding:2px 8px;'
        'border-radius:4px;font-size:11px;font-weight:700">✅ PAPER EXECUTED</span>'
    )

    # Account summary strip
    acct_html = ""
    if account:
        acct_html = f"""
<div style="background:#EEF2F7;border-radius:4px;padding:10px 16px;
            margin-bottom:12px;font-size:12px;color:#333;display:flex;gap:24px;flex-wrap:wrap">
  <div><span style="color:#666">Portfolio Value:</span>
       <strong>${account.get("equity",0):,.2f}</strong></div>
  <div><span style="color:#666">Cash:</span>
       <strong>${account.get("cash",0):,.2f}</strong></div>
  <div><span style="color:#666">Buying Power:</span>
       <strong>${account.get("buying_power",0):,.2f}</strong></div>
  <div><span style="color:#666">Account:</span>
       <strong>{"PAPER" if account.get("paper") else "⚠ LIVE"}</strong></div>
</div>"""

    def _decision_rows(decisions, accent):
        rows = ""
        for d in decisions:
            if d.action == "skip":
                icon, bg, status_txt = "—", "#F9F9F9", f"Skipped: {d.reason}"
                price_txt = ""
            elif d.executed:
                icon, bg = "✓", "#F0FFF6"
                r = d.order_result
                status_txt = f"Order {r.order_id[:8]}… | {r.status}"
                price_txt = (f"Entry: ${d.entry_price:.2f} | "
                             f"Stop: ${d.stop_loss:.2f} | "
                             f"TP: ${d.take_profit:.2f} | "
                             f"Qty: {d.qty:.4f} (~${d.size_usd:.0f})")
            else:
                icon, bg = "✗", "#FFF5F5"
                status_txt = f"Failed: {d.order_result.message if d.order_result else d.reason}"
                price_txt = ""

            rows += f"""
<tr style="background:{bg}">
  <td style="padding:6px 10px;font-weight:700;width:70px">{d.ticker}</td>
  <td style="padding:6px 10px;font-size:13px;font-weight:700;color:{accent}">{icon}</td>
  <td style="padding:6px 10px;font-size:12px">{status_txt}</td>
  <td style="padding:6px 10px;font-size:11px;color:#666">{price_txt}</td>
</tr>"""
        return rows

    all_decisions = bull_decisions + bear_decisions
    executed = sum(1 for d in all_decisions if d.executed)
    skipped  = sum(1 for d in all_decisions if d.action == "skip")
    failed   = sum(1 for d in all_decisions
                   if d.action != "skip" and not d.executed)

    bull_rows = _decision_rows(bull_decisions, "#1D6F42")
    bear_rows = _decision_rows(bear_decisions, "#9C0006")

    return f"""
<h2 style="color:#2E75B6;border-bottom:2px solid #C9D8F0;padding-bottom:8px;
           font-size:18px;margin:28px 0 16px">
  🤖 Alpaca Paper Trade Execution &nbsp;{mode_badge}
</h2>
{acct_html}
<div style="display:flex;gap:16px;margin-bottom:12px;flex-wrap:wrap">
  <div style="background:#F0FFF6;border-radius:4px;padding:8px 16px;font-size:12px">
    <strong style="color:#1D6F42">{executed}</strong> <span style="color:#666">executed</span>
  </div>
  <div style="background:#F9F9F9;border-radius:4px;padding:8px 16px;font-size:12px">
    <strong style="color:#888">{skipped}</strong> <span style="color:#666">skipped</span>
  </div>
  {"" if not failed else f'<div style="background:#FFF5F5;border-radius:4px;padding:8px 16px;font-size:12px"><strong style="color:#9C0006">{failed}</strong> <span style="color:#666">failed</span></div>'}
</div>
<table width="100%" cellpadding="0" cellspacing="0"
       style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:12px;
              border:1px solid #ddd;border-radius:6px;overflow:hidden">
  <thead>
    <tr style="background:#2E75B6;color:#fff">
      <th style="padding:8px 10px;text-align:left">Ticker</th>
      <th style="padding:8px 10px;text-align:center;width:40px">Status</th>
      <th style="padding:8px 10px;text-align:left">Details</th>
      <th style="padding:8px 10px;text-align:left">Levels</th>
    </tr>
  </thead>
  <tbody>
    {"" if not bull_decisions else f'<tr style="background:#E8F5E9"><td colspan="4" style="padding:5px 10px;font-weight:600;color:#1D6F42;font-size:11px">▲ BULLISH TRADES</td></tr>{bull_rows}'}
    {"" if not bear_decisions else f'<tr style="background:#FFEBEE"><td colspan="4" style="padding:5px 10px;font-weight:600;color:#9C0006;font-size:11px">▼ BEARISH TRADES</td></tr>{bear_rows}'}
  </tbody>
</table>
<div style="margin-top:8px;font-size:11px;color:#888">
  ⚠ Paper trading only. No real money involved. Not financial advice.
</div>"""


# ── Full HTML builder ─────────────────────────────────────────────────────────

def build_html(
    bulls: List[Tuple[TickerAnalysis, ConvictionScore]],
    bears: List[Tuple[TickerAnalysis, ConvictionScore]],
    all_results: List[TickerAnalysis],
    universe: str,
    bull_decisions: list = None,
    bear_decisions: list = None,
    account_summary: dict = None,
    dry_run: bool = True,
    scan_session: str = "",   # "premarket" | "afterhours" | "open" | "closed"
    conviction_map: dict = None,  # {ticker: ConvictionScore} for sector heatmap
) -> str:
    ts          = datetime.now().strftime("%A, %B %d, %Y  %H:%M ET")
    is_intraday = all_results and all_results[0].mode == "Hourly"

    # Session-aware labels
    session_labels = {
        "premarket":  ("Pre-Market Scan",  "Pre-market bars (4:00–9:30 AM ET)",      "Signals computed from pre-market quote data"),
        "afterhours": ("After-Hours Scan", "After-hours bars (4:00–8:00 PM ET)",      "Signals computed from after-hours quote data"),
        "open":       ("Market Hours Scan","Intraday 1-hour bars (last 3 months)",    "Market is open — signals from real-time hourly bars"),
        "closed":     ("Daily Scan",       "Daily bars (last 1 year)",                "Market is closed — signals from end-of-day bars"),
    }
    scan_label, data_mode, data_note = session_labels.get(
        scan_session,
        ("Market Scan",
         "Intraday 1-hour bars (last 3 months)" if is_intraday else "Daily bars (last 1 year)",
         "Market is open — signals computed from real-time hourly price bars" if is_intraday
         else "Market is closed — signals computed from end-of-day price bars")
    )
    bull_cards     = "".join(_pick_card(i + 1, ta, cs, "bullish") for i, (ta, cs) in enumerate(bulls))
    bear_cards     = "".join(_pick_card(i + 1, ta, cs, "bearish") for i, (ta, cs) in enumerate(bears))
    summary_table  = _section_table(all_results, f"Full Scan Results — {universe.upper()} ({len(all_results)} tickers)")
    heatmap_html   = build_heatmap_html(all_results, conviction_map)

    stat_items = [
        ("Scanned",          len(all_results),                                          "#1F3864"),
        ("Strong Bull (≥4)", sum(1 for r in all_results if r.net_score >= 4),           "#1D6F42"),
        ("Strong Bear (≤-4)",sum(1 for r in all_results if r.net_score <= -4),          "#9C0006"),
        ("Neutral",          sum(1 for r in all_results if -1 <= r.net_score <= 1),     "#666"),
    ]
    stats_html = "".join(
        f'<div style="text-align:center;padding:0 12px">'
        f'<div style="font-size:11px;color:#666;text-transform:uppercase;letter-spacing:0.5px">{lbl}</div>'
        f'<div style="font-size:20px;font-weight:700;color:{clr}">{val}</div></div>'
        for lbl, val, clr in stat_items
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trading Scanner Report</title></head>
<body style="margin:0;padding:0;background:#F4F4F4;font-family:Arial,sans-serif">
<div style="max-width:800px;margin:24px auto;background:#fff;border-radius:8px;
            overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08)">

  <div style="background:#1F3864;padding:24px 32px;color:#fff">
    <div style="font-size:22px;font-weight:700;letter-spacing:0.5px">📊 Trading Signal Scanner</div>
    <div style="margin-top:6px;font-size:14px;opacity:0.85">
      Universe: <strong>{universe.upper()}</strong> &nbsp;·&nbsp; {ts}
    </div>
    <div style="margin-top:6px;font-size:13px;background:rgba(255,255,255,0.12);
                border-radius:4px;padding:7px 12px;display:inline-block">
      📅 <strong>Data:</strong> {data_mode} &nbsp;·&nbsp; {data_note}
    </div>
    <div style="margin-top:6px;font-size:13px;opacity:0.7">
      {len(all_results)} tickers · {len(SIG_NAMES)} signals · Fibonacci projections · Full spreadsheet attached
    </div>
  </div>

  <div style="display:flex;background:#EEF2F7;padding:14px 32px;flex-wrap:wrap">{stats_html}</div>

  <div style="padding:24px 32px">

    <h2 style="color:#1D6F42;border-bottom:2px solid #C6EFCE;padding-bottom:8px;
               font-size:18px;margin-bottom:16px">
      ▲ Top {len(bulls)} Bullish Conviction Picks
    </h2>
    {bull_cards if bull_cards else '<p style="color:#888;font-size:13px">No strong bullish setups found.</p>'}

    <h2 style="color:#9C0006;border-bottom:2px solid #FFC7CE;padding-bottom:8px;
               font-size:18px;margin:28px 0 16px">
      ▼ Top {len(bears)} Bearish Conviction Picks
    </h2>
    {bear_cards if bear_cards else '<p style="color:#888;font-size:13px">No strong bearish setups found.</p>'}

    {summary_table}

    {heatmap_html}

  </div>

  <div style="background:#F4F4F4;padding:16px 32px;font-size:11px;color:#888;
              border-top:1px solid #ddd;line-height:1.7">
    Educational purposes only. Not financial advice. Fibonacci projections are probability
    zones, not guarantees. Always apply your own risk management.<br>
    <strong>Data:</strong> Real-time quotes — Financial Modeling Prep · OHLCV history — Yahoo Finance.
  </div>
</div>
</body></html>"""


# ── Send ──────────────────────────────────────────────────────────────────────

def send_email(
    bulls:           List[Tuple[TickerAnalysis, ConvictionScore]],
    bears:           List[Tuple[TickerAnalysis, ConvictionScore]],
    all_results:     List[TickerAnalysis],
    universe:        str,
    attachment:      Optional[Path] = None,
    bull_decisions:  list = None,
    bear_decisions:  list = None,
    account_summary: dict = None,
    dry_run:         bool = True,
    scan_session:    str  = "",
    conviction_map:  dict = None,  # {ticker: ConvictionScore} for heatmap
) -> bool:
    if not config.EMAIL_ENABLED:
        log.warning("Email not configured — check SMTP_USER, SMTP_PASSWORD, EMAIL_TO in .env")
        return False

    try:
        html_body = build_html(bulls, bears, all_results, universe, bull_decisions, bear_decisions, account_summary, dry_run, scan_session, conviction_map)

        msg = MIMEMultipart("mixed")
        # Session-aware subject prefix
        prefix_map = {
            "premarket":  "[PRE-MARKET] ",
            "afterhours": "[AFTER-HOURS] ",
            "open":       "[MARKET HOURS] ",
            "closed":     "[DAILY] ",
        }
        subject_prefix = prefix_map.get(scan_session, "")
        msg["Subject"] = subject_prefix + config.EMAIL_SUBJECT
        msg["From"]    = f"{config.EMAIL_FROM_NAME} <{config.EMAIL_FROM}>"
        msg["To"]      = ", ".join(config.EMAIL_TO)

        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText("Please view this email in an HTML-capable client.", "plain"))
        alt.attach(MIMEText(html_body, "html"))
        msg.attach(alt)

        if attachment and attachment.exists():
            with open(attachment, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{attachment.name}"')
            msg.attach(part)
            log.info("Attached spreadsheet: %s", attachment.name)

        if config.SMTP_PORT == 465:
            import ssl
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=context) as server:
                server.ehlo()
                server.login(config.SMTP_USER, config.SMTP_PASSWORD)
                server.sendmail(config.EMAIL_FROM, config.EMAIL_TO, msg.as_string())
        else:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(config.SMTP_USER, config.SMTP_PASSWORD)
                server.sendmail(config.EMAIL_FROM, config.EMAIL_TO, msg.as_string())

        log.info("Email sent to: %s", ", ".join(config.EMAIL_TO))
        return True

    except smtplib.SMTPAuthenticationError:
        log.error(
            "SMTP auth failed. For Gmail use an App Password: "
            "https://myaccount.google.com/apppasswords"
        )
    except smtplib.SMTPServerDisconnected as e:
        log.error("SMTP disconnected: %s — check SMTP_HOST / SMTP_PORT in .env", e)
    except smtplib.SMTPException as e:
        log.error("SMTP error: %s", e)
    except Exception as e:
        log.error("Email send failed: %s", e)
    return False
