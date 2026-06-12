"""
signals/news_sentiment.py — ENH-18: News sentiment signal.

Fetches recent headlines from FMP /stable/news/stock and scores them
using a lightweight keyword-based sentiment model. No external NLP
libraries required — pure Python, zero additional dependencies.

Sentiment scoring:
  Strong bull keywords (+2): beat, surge, breakout, record, raised, upgraded
  Mild bull keywords   (+1): growth, strong, positive, partnership, deal, wins
  Strong bear keywords (-2): miss, cut, downgrade, lawsuit, fraud, recall, loss
  Mild bear keywords   (-1): weak, slow, concern, risk, decline, disappoints

Bias logic:
  Aggregate score ≥ +3 from ≥2 articles  → BULL
  Aggregate score ≤ -3 from ≥2 articles  → BEAR
  Mixed / single article / weak score    → NEUTRAL

News is cached per ticker per scan run to avoid duplicate API calls.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from signals.base import Bias, SignalResult

log = logging.getLogger(__name__)

NAME = "News"

# ── Sentiment keyword dictionaries ────────────────────────────────────────────
_BULL_STRONG = {
    "beat", "beats", "surges", "surge", "breakout", "record", "raised",
    "upgraded", "upgrade", "outperform", "exceeded", "exceeds", "accelerates",
    "accelerating", "breakthrough", "buyout", "acquisition", "dividend",
    "authorized", "buyback", "approved", "wins", "won", "expands", "launched",
}
_BULL_MILD = {
    "growth", "grows", "growing", "strong", "stronger", "positive", "partnership",
    "deal", "agreement", "increases", "raised", "gaining", "gains", "recovering",
    "recovery", "momentum", "opportunity", "confident", "optimistic", "bullish",
    "innovation", "new", "contract", "investment",
}
_BEAR_STRONG = {
    "miss", "misses", "missed", "cut", "cuts", "downgrade", "downgrades",
    "downgraded", "lawsuit", "fraud", "recall", "recalled", "loss", "losses",
    "bankruptcy", "bankrupt", "default", "investigation", "probe", "violated",
    "fined", "layoffs", "layoff", "warns", "warning", "suspended", "suspended",
}
_BEAR_MILD = {
    "weak", "weaker", "slow", "slows", "slowing", "concern", "concerns",
    "risk", "risks", "risky", "decline", "declines", "declining", "disappoints",
    "disappointing", "disappointing", "uncertain", "uncertainty", "challenges",
    "headwinds", "pressure", "volatile", "volatility", "miss", "falling",
}

# Module-level cache: {ticker: (score, articles, fetched_at)}
_NEWS_CACHE: Dict[str, Tuple[int, List[str], datetime]] = {}
_CACHE_TTL_MINS = 30


def _score_text(text: str) -> int:
    """Score a headline/summary using keyword matching. Returns -4..+4."""
    words = set(text.lower().split())
    score = 0
    score += sum(2 for w in words if w in _BULL_STRONG)
    score += sum(1 for w in words if w in _BULL_MILD)
    score -= sum(2 for w in words if w in _BEAR_STRONG)
    score -= sum(1 for w in words if w in _BEAR_MILD)
    return max(-4, min(4, score))


def _fetch_news(ticker: str, limit: int = 10) -> List[Dict]:
    """Fetch news from FMP /stable/news/stock. Returns list of article dicts."""
    try:
        import requests
        import config
        resp = requests.get(
            "https://financialmodelingprep.com/stable/news/stock",
            params={"symbol": ticker, "limit": limit, "apikey": config.FMP_API_KEY},
            timeout=8,
        )
        if resp.status_code in (401, 403):
            log.debug("FMP news: plan restriction for %s", ticker)
            return []
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        log.debug("News fetch failed %s: %s", ticker, e)
        return []


def _get_cached_or_fetch(ticker: str) -> Tuple[int, List[str]]:
    """Return (aggregate_score, headline_list) using cache when fresh."""
    now = datetime.now()
    if ticker in _NEWS_CACHE:
        score, headlines, fetched_at = _NEWS_CACHE[ticker]
        if (now - fetched_at).total_seconds() < _CACHE_TTL_MINS * 60:
            return score, headlines

    articles = _fetch_news(ticker, limit=10)
    if not articles:
        _NEWS_CACHE[ticker] = (0, [], now)
        return 0, []

    total_score = 0
    headlines:  List[str] = []
    cutoff = now - timedelta(hours=48)   # only last 48 hours

    for art in articles:
        # Parse date
        date_str = art.get("publishedDate") or art.get("date") or ""
        try:
            art_dt = datetime.fromisoformat(date_str[:19])
            if art_dt < cutoff:
                continue
        except (ValueError, TypeError):
            pass  # include if date unparseable

        title   = art.get("title") or ""
        summary = art.get("text") or art.get("summary") or ""
        text    = f"{title} {summary}"

        score = _score_text(text)
        total_score += score
        headlines.append(f"{title[:80]} [{score:+d}]")

    _NEWS_CACHE[ticker] = (total_score, headlines[:5], now)
    return total_score, headlines[:5]


def analyze(ticker: str) -> SignalResult:
    """
    Compute news sentiment signal for a ticker.

    Args:
        ticker: stock symbol string (not bars — news is fetched independently)
    """
    score, headlines = _get_cached_or_fetch(ticker)

    n_articles = len(headlines)
    if n_articles == 0:
        return SignalResult(NAME, Bias.NEUTRAL, "No recent news",
                            "No headlines in last 48h or API unavailable")

    top = headlines[0] if headlines else ""
    detail = f"{n_articles} articles (48h) · score={score:+d} · {top}"

    if score >= 3 and n_articles >= 2:
        return SignalResult(NAME, Bias.BULL,
                            f"Positive sentiment (score={score:+d}, {n_articles} articles)",
                            detail)
    if score <= -3 and n_articles >= 2:
        return SignalResult(NAME, Bias.BEAR,
                            f"Negative sentiment (score={score:+d}, {n_articles} articles)",
                            detail)

    # Single strongly positive article
    if score >= 4 and n_articles >= 1:
        return SignalResult(NAME, Bias.BULL, f"Strong positive headline (score={score:+d})", detail)
    if score <= -4 and n_articles >= 1:
        return SignalResult(NAME, Bias.BEAR, f"Strong negative headline (score={score:+d})", detail)

    return SignalResult(NAME, Bias.NEUTRAL,
                        f"Mixed/neutral news (score={score:+d}, {n_articles} articles)",
                        detail)
