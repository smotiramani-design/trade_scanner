"""
utils/email_sender.py — sends a rich HTML email with:
  • Top 5 bullish + bearish conviction picks
  • Per-ticker signal breakdown table
  • Inline analysis commentary
  • Full scan results spreadsheet attached
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
from signals.conviction import ConvictionScore

log = logging.getLogger(__name__)

SIG_NAMES = ["Candle", "Volume", "SMA", "Gaps", "Stoch", "CCI", "RR"]


# ── HTML helpers ──────────────────────────────────────────────────────────────

def _bias_dot(bias: str) -> str:
    colors = {"bull": "#1D9E75", "bear": "#D85A30", "neutral": "#888"}
    icons  = {"bull": "▲", "bear": "▼", "neutral": "—"}
    c = colors.get(bias, "#888")
    i = icons.get(bias, "—")
    return f'<span style="color:{c};font-weight:700">{i}</span>'


def _grade_badge(grade: str) -> str:
    colors = {
        "A+": ("#FFFFFF", "#1D6F42"),
        "A":  ("#FFFFFF", "#2D9E5F"),
        "B":  ("#27500A", "#C6EFCE"),
        "C":  ("#633806", "#FAEEDA"),
        "D":  ("#888",    "#F2F2F2"),
    }
    fg, bg = colors.get(grade, ("#000", "#eee"))
    return (f'<span style="background:{bg};color:{fg};padding:2px 8px;'
            f'border-radius:4px;font-weight:700;font-size:12px">{grade}</span>')


def _conviction_bar(pct: float, direction: str) -> str:
    color = "#1D9E75" if direction == "bullish" else "#D85A30" if direction == "bearish" else "#888"
    w = min(int(pct), 100)
    return (f'<div style="background:#eee;border-radius:3px;height:8px;width:120px;display:inline-block;vertical-align:middle">'
            f'<div style="background:{color};width:{w}%;height:100%;border-radius:3px"></div></div>'
            f' <span style="font-size:12px;color:{color};font-weight:600">{pct:.0f}%</span>')


def _signal_chips(ta: TickerAnalysis) -> str:
    chips = []
    for i, sig in enumerate(ta.signals):
        name = SIG_NAMES[i] if i < len(SIG_NAMES) else ""
        c = {"bull": "#C6EFCE", "bear": "#FFC7CE", "neutral": "#F2F2F2"}.get(sig.bias.value, "#eee")
        tc = {"bull": "#1D6F42", "bear": "#9C0006", "neutral": "#666"}.get(sig.bias.value, "#333")
        chips.append(
            f'<span style="background:{c};color:{tc};border-radius:4px;'
            f'padding:2px 6px;font-size:11px;margin:2px;display:inline-block">'
            f'{_bias_dot(sig.bias.value)} {name}</span>'
        )
    return "".join(chips)


def _pick_card(rank: int, ta: TickerAnalysis, cs: ConvictionScore, direction: str) -> str:
    accent = "#1D6F42" if direction == "bullish" else "#9C0006"
    bg     = "#F0FFF6" if direction == "bullish" else "#FFF5F5"
    chg_c  = "#1D9E75" if (ta.chg_pct or 0) >= 0 else "#D85A30"
    chg_s  = f"{ta.chg_pct:+.2f}%" if ta.chg_pct else "—"
    price_s = f"${ta.price:.2f}" if ta.price else "—"

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
        &nbsp;&nbsp;
        <span style="font-size:16px;color:#333;font-weight:600">{price_s}</span>
        &nbsp;
        <span style="font-size:14px;color:{chg_c};font-weight:600">{chg_s}</span>
      </td>
      <td align="right">
        {_grade_badge(cs.grade)}
        &nbsp;
        <span style="font-size:12px;color:#666">Score: <strong style="color:{accent}">{ta.net_score:+d}/7</strong></span>
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
</div>"""


def _section_table(results: List[TickerAnalysis], title: str, limit: int = 20) -> str:
    rows_html = ""
    for i, ta in enumerate(results[:limit]):
        bg       = "#fff" if i % 2 == 0 else "#F9F9F9"
        sig_dots = "".join(_bias_dot(s.bias.value) for s in ta.signals)
        score_c  = "#1D9E75" if ta.net_score > 0 else "#D85A30" if ta.net_score < 0 else "#888"
        chg_c    = "#1D9E75" if (ta.chg_pct or 0) >= 0 else "#D85A30"
        price_s  = f"${ta.price:.2f}" if ta.price else "—"
        chg_s    = f"{ta.chg_pct:+.2f}%" if ta.chg_pct is not None else "—"
        score_s  = f"{ta.net_score:+d}"
        rows_html += f"""
<tr style="background:{bg}">
  <td style="padding:7px 10px;font-weight:700;font-size:13px">{ta.ticker}</td>
  <td style="padding:7px 10px;text-align:right">{price_s}</td>
  <td style="padding:7px 10px;text-align:right;color:{chg_c}">{chg_s}</td>
  <td style="padding:7px 10px;text-align:center;color:{score_c};font-weight:700">{score_s}</td>
  <td style="padding:7px 10px;text-align:center">{ta.bull_count}</td>
  <td style="padding:7px 10px;text-align:center">{ta.bear_count}</td>
  <td style="padding:7px 10px;letter-spacing:3px">{sig_dots}</td>
  <td style="padding:7px 10px;font-size:12px;color:#555">{ta.verdict}</td>
</tr>"""

    return f"""
<h3 style="font-family:Arial,sans-serif;color:#1F3864;margin:24px 0 8px">{title}</h3>
<table width="100%" cellpadding="0" cellspacing="0"
       style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:13px;
              border:1px solid #ddd;border-radius:6px;overflow:hidden">
  <thead>
    <tr style="background:#1F3864;color:#fff">
      <th style="padding:9px 10px;text-align:left">Ticker</th>
      <th style="padding:9px 10px;text-align:right">Price</th>
      <th style="padding:9px 10px;text-align:right">Chg %</th>
      <th style="padding:9px 10px;text-align:center">Score</th>
      <th style="padding:9px 10px;text-align:center">Bull</th>
      <th style="padding:9px 10px;text-align:center">Bear</th>
      <th style="padding:9px 10px">Signals</th>
      <th style="padding:9px 10px">Verdict</th>
    </tr>
  </thead>
  <tbody>{rows_html}</tbody>
</table>"""


def build_html(
    bulls: List[Tuple[TickerAnalysis, ConvictionScore]],
    bears: List[Tuple[TickerAnalysis, ConvictionScore]],
    all_results: List[TickerAnalysis],
    universe: str,
) -> str:
    ts = datetime.now().strftime("%A, %B %d, %Y  %H:%M ET")
    mode = "Intraday (Hourly)" if all_results and all_results[0].mode == "Hourly" else "End-of-Day (Daily)"
    bull_cards = "".join(_pick_card(i + 1, ta, cs, "bullish")  for i, (ta, cs) in enumerate(bulls))
    bear_cards = "".join(_pick_card(i + 1, ta, cs, "bearish") for i, (ta, cs) in enumerate(bears))
    summary_table = _section_table(all_results, f"Full Scan Results — {universe.upper()} ({len(all_results)} tickers)")

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trading Scanner Report</title></head>
<body style="margin:0;padding:0;background:#F4F4F4;font-family:Arial,sans-serif">
<div style="max-width:760px;margin:24px auto;background:#fff;border-radius:8px;
            overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08)">

  <!-- Header -->
  <div style="background:#1F3864;padding:24px 32px;color:#fff">
    <div style="font-size:22px;font-weight:700;letter-spacing:0.5px">
      📊 Trading Signal Scanner
    </div>
    <div style="margin-top:6px;font-size:14px;opacity:0.85">
      Universe: <strong>{universe.upper()}</strong> &nbsp;·&nbsp;
      Mode: <strong>{mode}</strong> &nbsp;·&nbsp;
      {ts}
    </div>
    <div style="margin-top:4px;font-size:13px;opacity:0.7">
      {len(all_results)} tickers scanned · 7-signal analysis ·
      Full results attached as spreadsheet
    </div>
  </div>

  <!-- Stats strip -->
  <div style="display:flex;background:#EEF2F7;padding:12px 32px;gap:24px;flex-wrap:wrap">
    {"".join(f'<div style="text-align:center"><div style="font-size:11px;color:#666;text-transform:uppercase;letter-spacing:0.5px">{lbl}</div><div style="font-size:20px;font-weight:700;color:{clr}">{val}</div></div>'
      for lbl, val, clr in [
        ("Scanned", len(all_results), "#1F3864"),
        ("Strong Bull (≥4)", sum(1 for r in all_results if r.net_score >= 4), "#1D6F42"),
        ("Strong Bear (≤-4)", sum(1 for r in all_results if r.net_score <= -4), "#9C0006"),
        ("Neutral", sum(1 for r in all_results if -1 <= r.net_score <= 1), "#666"),
      ])}
  </div>

  <div style="padding:24px 32px">

    <!-- Top Bullish -->
    <h2 style="color:#1D6F42;border-bottom:2px solid #C6EFCE;padding-bottom:8px;
               font-size:18px;margin-bottom:16px">
      ▲ Top {len(bulls)} Bullish Conviction Picks
    </h2>
    {bull_cards if bull_cards else '<p style="color:#888;font-size:13px">No strong bullish setups found.</p>'}

    <!-- Top Bearish -->
    <h2 style="color:#9C0006;border-bottom:2px solid #FFC7CE;padding-bottom:8px;
               font-size:18px;margin:28px 0 16px">
      ▼ Top {len(bears)} Bearish Conviction Picks
    </h2>
    {bear_cards if bear_cards else '<p style="color:#888;font-size:13px">No strong bearish setups found.</p>'}

    {summary_table}

  </div>

  <!-- Footer -->
  <div style="background:#F4F4F4;padding:16px 32px;font-size:11px;color:#888;
              border-top:1px solid #ddd;line-height:1.7">
    This report is generated automatically by Trading Signal Scanner for educational purposes only.
    It does not constitute financial advice. Always apply your own risk management before trading.
    Past signals are not indicative of future results.<br>
    <strong>Data sources:</strong> Real-time quotes from Financial Modeling Prep · Historical OHLCV from Yahoo Finance.
  </div>
</div>
</body></html>"""


def send_email(
    bulls:       List[Tuple[TickerAnalysis, ConvictionScore]],
    bears:       List[Tuple[TickerAnalysis, ConvictionScore]],
    all_results: List[TickerAnalysis],
    universe:    str,
    attachment:  Optional[Path] = None,
) -> bool:
    """Build and send the HTML email. Returns True on success."""
    if not config.EMAIL_ENABLED:
        log.warning("Email not configured — skipping. Check SMTP_USER, SMTP_PASSWORD, EMAIL_TO in .env")
        return False

    try:
        html_body = build_html(bulls, bears, all_results, universe)

        msg = MIMEMultipart("mixed")
        msg["Subject"] = config.EMAIL_SUBJECT
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
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{attachment.name}"'
            )
            msg.attach(part)
            log.info("Attached spreadsheet: %s", attachment.name)

        if config.SMTP_PORT == 465:
            # SSL from the start (port 465)
            import ssl
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=context) as server:
                server.ehlo()
                server.login(config.SMTP_USER, config.SMTP_PASSWORD)
                server.sendmail(config.EMAIL_FROM, config.EMAIL_TO, msg.as_string())
        else:
            # STARTTLS (port 587) — correct sequence:
            # connect -> ehlo -> starttls -> ehlo again -> login -> send
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
            "SMTP authentication failed. "
            "For Gmail use an App Password (not your account password): "
            "https://myaccount.google.com/apppasswords"
        )
    except smtplib.SMTPServerDisconnected as e:
        log.error("SMTP server disconnected: %s — check SMTP_HOST / SMTP_PORT in .env", e)
    except smtplib.SMTPException as e:
        log.error("SMTP error: %s", e)
    except Exception as e:
        log.error("Email send failed: %s", e)
    return False
