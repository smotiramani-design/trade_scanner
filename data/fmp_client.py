"""
data/fmp_client.py — Financial Modeling Prep real-time quote fetcher.
Docs: https://financialmodelingprep.com/developer/docs/
"""
import logging
import time
from typing import Dict, List, Optional

import requests

import config

log = logging.getLogger(__name__)

BASE = "https://financialmodelingprep.com/api/v3"
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "trading-scanner/1.0"})


class FMPError(Exception):
    pass


def get_quotes(tickers: List[str]) -> List[Dict]:
    """
    Fetch real-time quotes for a list of tickers.
    Returns a list of dicts with keys: symbol, price, changesPercentage,
    volume, avgVolume, marketCap, pe, eps, etc.
    """
    if not tickers:
        return []
    symbols = ",".join(tickers)
    url = f"{BASE}/quote/{symbols}"
    params = {"apikey": config.FMP_API_KEY}
    try:
        resp = _SESSION.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "Error Message" in data:
            raise FMPError(data["Error Message"])
        return data if isinstance(data, list) else []
    except requests.RequestException as e:
        log.error("FMP quote request failed: %s", e)
        raise FMPError(str(e)) from e


def get_quotes_batched(tickers: List[str], batch_size: int = None) -> Dict[str, Dict]:
    """
    Fetch quotes for a large ticker list in batches.
    Returns a dict keyed by symbol.
    """
    bs = batch_size or config.FMP_BATCH_SIZE
    result: Dict[str, Dict] = {}
    for i in range(0, len(tickers), bs):
        batch = tickers[i : i + bs]
        log.debug("FMP batch %d–%d: %s", i + 1, i + len(batch), batch)
        quotes = get_quotes(batch)
        for q in quotes:
            result[q["symbol"]] = q
        if i + bs < len(tickers):
            time.sleep(0.2)
    return result


def get_sp500_constituents() -> List[str]:
    """Fetch live S&P 500 constituent list from FMP."""
    url = f"{BASE}/sp500_constituent"
    try:
        resp = _SESSION.get(url, params={"apikey": config.FMP_API_KEY}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return [d["symbol"] for d in data if "symbol" in d]
    except Exception as e:
        log.warning("Could not fetch live S&P 500 list: %s. Using built-in list.", e)
        return []


def get_nasdaq100_constituents() -> List[str]:
    """Fetch live Nasdaq 100 constituent list from FMP."""
    url = f"{BASE}/nasdaq_constituent"
    try:
        resp = _SESSION.get(url, params={"apikey": config.FMP_API_KEY}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return [d["symbol"] for d in data if "symbol" in d]
    except Exception as e:
        log.warning("Could not fetch live Nasdaq 100 list: %s. Using built-in list.", e)
        return []


def get_dowjones_constituents() -> List[str]:
    """Fetch live Dow Jones 30 constituent list from FMP."""
    url = f"{BASE}/dowjones_constituent"
    try:
        resp = _SESSION.get(url, params={"apikey": config.FMP_API_KEY}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return [d["symbol"] for d in data if "symbol" in d]
    except Exception as e:
        log.warning("Could not fetch live Dow Jones list: %s. Using built-in list.", e)
        return []
