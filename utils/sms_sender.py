"""
utils/sms_sender.py — sends a concise SMS via Twilio with the
top 5 conviction picks (bullish and bearish) and key stats.

Twilio free trial: https://www.twilio.com/try-twilio
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Tuple

import config
from signals.base import TickerAnalysis
from signals.conviction import ConvictionScore

log = logging.getLogger(__name__)

MAX_SMS_CHARS = 1600   # Twilio limit per message segment * 10 safety cap


def _build_sms(
    bulls:    List[Tuple[TickerAnalysis, ConvictionScore]],
    bears:    List[Tuple[TickerAnalysis, ConvictionScore]],
    universe: str,
    total:    int,
) -> str:
    ts    = datetime.now().strftime("%m/%d %H:%M ET")
    lines = [
        f"📊 Trading Scanner — {universe.upper()} — {ts}",
        f"Scanned: {total} tickers",
        "",
    ]

    if bulls:
        lines.append("▲ TOP BULLISH PICKS:")
        for i, (ta, cs) in enumerate(bulls, 1):
            price = f"${ta.price:.2f}" if ta.price else "N/A"
            chg   = f"{ta.chg_pct:+.1f}%" if ta.chg_pct else ""
            lines.append(
                f"  {i}. {ta.ticker} {price} {chg} | Score:{ta.net_score:+d} "
                f"| Grade:{cs.grade} | Conv:{cs.conviction_pct:.0f}%"
            )
    else:
        lines.append("▲ No strong bullish picks.")

    lines.append("")

    if bears:
        lines.append("▼ TOP BEARISH PICKS:")
        for i, (ta, cs) in enumerate(bears, 1):
            price = f"${ta.price:.2f}" if ta.price else "N/A"
            chg   = f"{ta.chg_pct:+.1f}%" if ta.chg_pct else ""
            lines.append(
                f"  {i}. {ta.ticker} {price} {chg} | Score:{ta.net_score:+d} "
                f"| Grade:{cs.grade} | Conv:{cs.conviction_pct:.0f}%"
            )
    else:
        lines.append("▼ No strong bearish picks.")

    lines += [
        "",
        "Full report sent via email. Not financial advice.",
    ]

    msg = "\n".join(lines)
    if len(msg) > MAX_SMS_CHARS:
        msg = msg[:MAX_SMS_CHARS - 3] + "..."
    return msg


def send_sms(
    bulls:    List[Tuple[TickerAnalysis, ConvictionScore]],
    bears:    List[Tuple[TickerAnalysis, ConvictionScore]],
    universe: str,
    total:    int,
) -> bool:
    """Send SMS alert to all configured numbers. Returns True if all succeed."""
    if not config.SMS_ENABLED:
        log.warning(
            "SMS not configured — skipping. "
            "Check TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, SMS_TO_NUMBERS in .env"
        )
        return False

    try:
        from twilio.rest import Client  # lazy import — optional dependency
    except ImportError:
        log.error("twilio package not installed. Run: pip install twilio")
        return False

    body = _build_sms(bulls, bears, universe, total)
    log.debug("SMS body (%d chars):\n%s", len(body), body)

    client  = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
    success = True

    for number in config.SMS_TO_NUMBERS:
        try:
            message = client.messages.create(
                body=body,
                from_=config.TWILIO_FROM_NUMBER,
                to=number,
            )
            log.info("SMS sent to %s — SID: %s", number, message.sid)
        except Exception as e:
            log.error("SMS to %s failed: %s", number, e)
            success = False

    return success
