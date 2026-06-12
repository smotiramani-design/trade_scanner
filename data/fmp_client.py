"""
data/fmp_client.py — Financial Modeling Prep API client (/stable/ endpoints).

Price source selection by session
───────────────────────────────────
  Pre-market   (4:00 AM – 9:30 AM ET, weekdays)
    → /stable/premarket-quote   → last_sale_price / ask
    → fallback: previousClose from /stable/quote

  Market open  (9:30 AM – 4:00 PM ET, weekdays)
    → /stable/quote             → price  (real-time tick)

  After-hours  (4:00 PM – 8:00 PM ET, weekdays)
    → /stable/aftermarket-quote → last_sale_price / ask
    → fallback: price from /stable/quote (some providers push AH price here)

  Closed       (overnight / weekends)
    → /stable/quote             → previousClose

  Final fallback (all sessions): last OHLCV bar close from Yahoo Finance

Endpoint map (all /stable/ base):
  /stable/quote                       — real-time + EOD quote (all plans)
  /stable/premarket-quote             — pre-market bid/ask/last (paid plan)
  /stable/aftermarket-quote           — after-hours bid/ask/last (paid plan)
  /stable/historical-chart/{interval} — intraday OHLCV (Ultimate plan)
  /stable/sp500-constituent           — S&P 500 constituent list (paid plan)
  /stable/nasdaq-constituent          — Nasdaq 100 constituent list (paid plan)
  /stable/dowjones-constituent        — Dow Jones constituent list (paid plan)
"""
import logging
import time
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

import requests

import config

log = logging.getLogger(__name__)

BASE     = "https://financialmodelingprep.com/stable"
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "trading-scanner/1.0"})

_PLAN_RESTRICTED = {401, 403}


class FMPError(Exception):
    pass


# ── Session detection ─────────────────────────────────────────────────────────

class MarketSession(Enum):
    PREMARKET   = "premarket"    # 4:00 AM – 9:30 AM ET (weekdays)
    OPEN        = "open"         # 9:30 AM – 4:00 PM ET (weekdays)
    AFTERHOURS  = "afterhours"   # 4:00 PM – 8:00 PM ET (weekdays)
    CLOSED      = "closed"       # overnight / weekends


def get_market_session() -> MarketSession:
    """Return the current US equity market session."""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(tz=ZoneInfo("America/New_York"))
    except ImportError:
        import pytz
        now = datetime.now(tz=pytz.timezone("America/New_York"))

    if now.weekday() >= 5:
        return MarketSession.CLOSED

    mins = now.hour * 60 + now.minute
    if   240 <= mins < 570:   return MarketSession.PREMARKET   # 4:00–9:30
    elif 570 <= mins < 960:   return MarketSession.OPEN         # 9:30–16:00
    elif 960 <= mins < 1200:  return MarketSession.AFTERHOURS   # 16:00–20:00
    else:                     return MarketSession.CLOSED


def _is_market_open() -> bool:
    return get_market_session() == MarketSession.OPEN


# ── Extended-hours quote endpoints ────────────────────────────────────────────

def _fetch_extended_quotes(endpoint: str, tickers: List[str]) -> Dict[str, Dict]:
    """
    Generic fetcher for premarket-quote and aftermarket-quote endpoints.
    Both accept ?symbol=X,Y,Z and return the same schema:
      symbol, ask, bid, asize, bsize, volume, last_sale_price, last_sale_time
    Silent fallback on plan restriction (401/403).
    """
    if not tickers:
        return {}
    result: Dict[str, Dict] = {}
    # Both endpoints support comma-separated symbols in one call
    try:
        resp = _SESSION.get(
            f"{BASE}/{endpoint}",
            params={"symbol": ",".join(tickers), "apikey": config.FMP_API_KEY},
            timeout=10,
        )
        if resp.status_code in _PLAN_RESTRICTED:
            log.debug("%s: plan restriction (HTTP %d) — falling back to /quote", endpoint, resp.status_code)
            return {}
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            for q in data:
                sym = q.get("symbol")
                if sym:
                    result[sym] = q
        log.debug("%s: received %d quotes", endpoint, len(result))
    except requests.RequestException as e:
        log.debug("%s fetch failed: %s", endpoint, e)
    return result


def get_premarket_extended(tickers: List[str]) -> Dict[str, Dict]:
    """
    Fetch pre-market quotes via /stable/premarket-quote.
    Active 4:00 AM – 9:30 AM ET on trading days.
    Returns {symbol: {ask, bid, asize, bsize, volume, last_sale_price, last_sale_time}}
    """
    return _fetch_extended_quotes("premarket-quote", tickers)


def get_aftermarket_extended(tickers: List[str]) -> Dict[str, Dict]:
    """
    Fetch after-hours quotes via /stable/aftermarket-quote.
    Active 4:00 PM – 8:00 PM ET on trading days.
    Returns {symbol: {ask, bid, asize, bsize, volume, last_sale_price, last_sale_time}}
    """
    return _fetch_extended_quotes("aftermarket-quote", tickers)


# ── Standard quote ─────────────────────────────────────────────────────────────

def get_quotes(tickers: List[str]) -> List[Dict]:
    """
    Real-time quotes via GET /stable/quote?symbol=...
    Fields: symbol, price, changesPercentage, volume, dayHigh, dayLow,
            previousClose, open, preMarketPrice, yearHigh, yearLow, etc.
    Available on all plans including free.
    """
    if not tickers:
        return []
    try:
        resp = _SESSION.get(
            f"{BASE}/quote",
            params={"symbol": ",".join(tickers), "apikey": config.FMP_API_KEY},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "Error Message" in data:
            raise FMPError(data["Error Message"])
        return data if isinstance(data, list) else []
    except requests.RequestException as e:
        log.error("FMP quote request failed: %s", e)
        raise FMPError(str(e)) from e


def get_quotes_batched(tickers: List[str], batch_size: int = None) -> Dict[str, Dict]:
    """Fetch standard quotes in batches. Returns {symbol: quote_dict}."""
    bs     = batch_size or config.FMP_BATCH_SIZE
    result: Dict[str, Dict] = {}
    for i in range(0, len(tickers), bs):
        batch = tickers[i: i + bs]
        log.debug("FMP quote batch %d–%d", i + 1, i + len(batch))
        for q in get_quotes(batch):
            result[q["symbol"]] = q
        if i + bs < len(tickers):
            time.sleep(0.2)
    return result


# ── Price extraction ──────────────────────────────────────────────────────────

def _best_extended_price(ext_quote: Dict) -> float:
    """
    Extract the best price from a premarket or aftermarket quote.
    Priority: last_sale_price → ask → bid → 0
    """
    for field in ("last_sale_price", "lastSalePrice", "ask", "bid"):
        val = ext_quote.get(field)
        if val:
            try:
                f = float(val)
                if f > 0:
                    return f
            except (ValueError, TypeError):
                continue
    return 0.0


def extract_price(
    quote:     Dict,
    session:   Optional[MarketSession] = None,
    ext_quote: Optional[Dict] = None,   # pre/after-market quote if available
) -> float:
    """
    Extract the best available price for the current market session.

    Session   Source priority
    ────────  ──────────────────────────────────────────────────────────
    OPEN      quote.price  → quote.previousClose → 0
    PREMARKET ext_quote (premarket-quote) → quote.preMarketPrice
              → quote.price → quote.previousClose → 0
    AFTERHOURS ext_quote (aftermarket-quote) → quote.price (some
              providers push AH here) → quote.previousClose → 0
    CLOSED    quote.previousClose → quote.price → 0

    Returns 0.0 when nothing is available — scanner falls back to bar close.
    """
    if session is None:
        session = get_market_session()

    rt_price   = float(quote.get("price")          or 0)
    prev_close = float(quote.get("previousClose")  or 0)
    pre_mkt    = float(quote.get("preMarketPrice") or 0)

    if session == MarketSession.OPEN:
        return rt_price if rt_price > 0 else prev_close

    if session == MarketSession.PREMARKET:
        # Try dedicated premarket endpoint first
        if ext_quote:
            p = _best_extended_price(ext_quote)
            if p > 0:
                log.debug("Using premarket-quote price: $%.2f", p)
                return p
        # Fallback: preMarketPrice field from /stable/quote
        if pre_mkt > 0:
            return pre_mkt
        # Last resort: previous close
        return prev_close if prev_close > 0 else rt_price

    if session == MarketSession.AFTERHOURS:
        # Try dedicated aftermarket endpoint first
        if ext_quote:
            p = _best_extended_price(ext_quote)
            if p > 0:
                log.debug("Using aftermarket-quote price: $%.2f", p)
                return p
        # Some providers update quote.price after hours
        if rt_price > 0:
            return rt_price
        return prev_close

    # CLOSED (overnight / weekend)
    return prev_close if prev_close > 0 else rt_price


def extract_chg_pct(
    quote:     Dict,
    session:   Optional[MarketSession] = None,
    ext_quote: Optional[Dict] = None,
) -> float:
    """
    Extract % change vs previous close, appropriate for current session.
    """
    if session is None:
        session = get_market_session()

    # During regular hours changesPercentage is accurate
    if session == MarketSession.OPEN:
        chg = float(quote.get("changesPercentage") or 0)
        if chg != 0:
            return chg

    # For all other sessions, calculate from best price vs previousClose
    price = extract_price(quote, session, ext_quote)
    prev  = float(quote.get("previousClose") or 0)
    if price > 0 and prev > 0:
        return round((price - prev) / prev * 100, 4)
    return 0.0


def extract_session_label(session: Optional[MarketSession] = None) -> str:
    """Human-readable label for logging and display."""
    if session is None:
        session = get_market_session()
    return {
        MarketSession.PREMARKET:  "Pre-market",
        MarketSession.OPEN:       "Market open",
        MarketSession.AFTERHOURS: "After-hours",
        MarketSession.CLOSED:     "Market closed",
    }[session]


# ── Fibonacci anchor data ─────────────────────────────────────────────────────

def get_extended_anchor_data(tickers: List[str]) -> Dict[str, Dict]:
    """
    Fetch the most appropriate extended-hours quote for Fibonacci anchor,
    based on current market session.
    Also fetches day high/low from standard quote for session range.
    Returns {symbol: {day_high, day_low, prev_close, ext_price, session}}
    """
    session = get_market_session()
    result:  Dict[str, Dict] = {}

    # Always fetch standard quote for dayHigh/dayLow/previousClose
    try:
        standard = get_quotes_batched(tickers)
    except FMPError:
        standard = {}

    # Fetch extended-hours quote when applicable
    ext_quotes: Dict[str, Dict] = {}
    if session == MarketSession.PREMARKET:
        ext_quotes = get_premarket_extended(tickers)
        log.info("Session: Pre-market — fetching premarket-quote for %d tickers", len(tickers))
    elif session == MarketSession.AFTERHOURS:
        ext_quotes = get_aftermarket_extended(tickers)
        log.info("Session: After-hours — fetching aftermarket-quote for %d tickers", len(tickers))
    else:
        log.debug("Session: %s — no extended-hours quotes needed", session.value)

    for sym in tickers:
        q   = standard.get(sym, {})
        ext = ext_quotes.get(sym, {})
        result[sym] = {
            "day_high":   q.get("dayHigh"),
            "day_low":    q.get("dayLow"),
            "prev_close": q.get("previousClose"),
            "ext_price":  _best_extended_price(ext) if ext else None,
            "session":    session.value,
            "_ext_raw":   ext,   # raw extended quote for price extraction
            "_std_raw":   q,     # raw standard quote
        }

    return result


# ── Intraday OHLCV (Ultimate plan) ────────────────────────────────────────────

def get_intraday_bars(
    ticker:   str,
    interval: str = "1hour",
    days:     int = 90,
) -> List[Dict]:
    """
    Intraday OHLCV via /stable/historical-chart/{interval}?symbol=X
    Returns list of {date, open, high, low, close, volume}, newest first.
    """
    to_dt   = datetime.now()
    from_dt = to_dt - timedelta(days=days)
    try:
        resp = _SESSION.get(
            f"{BASE}/historical-chart/{interval}",
            params={
                "symbol": ticker,
                "from":   from_dt.strftime("%Y-%m-%d"),
                "to":     to_dt.strftime("%Y-%m-%d"),
                "apikey": config.FMP_API_KEY,
            },
            timeout=15,
        )
        if resp.status_code in _PLAN_RESTRICTED:
            log.debug("FMP intraday %s/%s: plan restriction — using yfinance", interval, ticker)
            return []
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "Error Message" in data:
            return []
        return data if isinstance(data, list) else []
    except requests.RequestException as e:
        log.debug("FMP intraday fetch failed %s: %s", ticker, e)
        return []



# ── Earnings calendar (ENH-11) ────────────────────────────────────────────────

def get_earnings_flags(
    tickers:    List[str],
    days_ahead: int = 2,
) -> Dict[str, bool]:
    """
    Fetch the FMP earnings calendar and return {symbol: True} for any ticker
    with an earnings release within `days_ahead` trading days.

    Prevents entering new positions the day before or day-of earnings —
    a major risk management gap since earnings cause 5-15% gaps.

    Uses /stable/earning-calendar endpoint. Silent fallback on plan restriction.
    """
    import datetime as dt_mod
    from datetime import timezone as tz

    result: Dict[str, bool] = {t: False for t in tickers}
    if not tickers:
        return result

    try:
        today = dt_mod.date.today()
        to_dt = today + dt_mod.timedelta(days=days_ahead + 3)   # add buffer for weekends

        resp = _SESSION.get(
            f"{BASE}/earning-calendar",
            params={
                "from":   today.strftime("%Y-%m-%d"),
                "to":     to_dt.strftime("%Y-%m-%d"),
                "apikey": config.FMP_API_KEY,
            },
            timeout=10,
        )
        if resp.status_code in _PLAN_RESTRICTED:
            log.debug("earning-calendar: plan restriction — earnings flags unavailable")
            return result

        resp.raise_for_status()
        data = resp.json()

        ticker_set = set(tickers)
        if isinstance(data, list):
            for item in data:
                sym = (item.get("symbol") or "").strip()
                if sym in ticker_set:
                    # Check if earnings date is within days_ahead business days
                    try:
                        earn_date = dt_mod.date.fromisoformat(
                            (item.get("date") or item.get("reportDate") or "")[:10]
                        )
                        delta = (earn_date - today).days
                        if 0 <= delta <= days_ahead + 2:    # +2 for weekend buffer
                            result[sym] = True
                            log.info("Earnings within %d days: %s on %s",
                                     days_ahead, sym, earn_date)
                    except (ValueError, TypeError):
                        continue

    except Exception as e:
        log.debug("Earnings calendar fetch failed: %s", e)

    flagged = sum(1 for v in result.values() if v)
    if flagged:
        log.info("Earnings flags: %d tickers with upcoming earnings", flagged)
    return result

# ── Constituent list helpers ──────────────────────────────────────────────────

def _fetch_constituent(path: str, label: str) -> List[str]:
    """Fetch index constituent list. Silent fallback on plan restriction."""
    try:
        resp = _SESSION.get(
            f"{BASE}/{path}",
            params={"apikey": config.FMP_API_KEY},
            timeout=15,
        )
        if resp.status_code in _PLAN_RESTRICTED:
            log.debug("%s constituent: plan restriction — using built-in", label)
            return []
        resp.raise_for_status()
        data    = resp.json()
        tickers = [d["symbol"] for d in data if isinstance(d, dict) and "symbol" in d]
        if tickers:
            log.info("Live %s list: %d tickers", label, len(tickers))
        return tickers
    except Exception as e:
        log.debug("%s constituent fetch failed (%s) — using built-in", label, e)
        return []


def get_sp500_constituents()     -> List[str]: return _fetch_constituent("sp500-constituent",    "S&P 500")
def get_nasdaq100_constituents() -> List[str]: return _fetch_constituent("nasdaq-constituent",   "Nasdaq 100")
def get_dowjones_constituents()  -> List[str]: return _fetch_constituent("dowjones-constituent", "Dow Jones")

# ── Company name lookup ───────────────────────────────────────────────────────

_NAME_CACHE: Dict[str, str] = {}   # module-level cache populated at first call


def get_company_names(tickers: List[str]) -> Dict[str, str]:
    """
    Return {symbol: company_name} for a list of tickers.

    Strategy (in order of priority):
      1. Static lookup table (data/company_names.py) — instant, always works,
         covers all ~517 tickers in the standard universes.
      2. FMP /stable/profile endpoint — for any tickers not in the static table,
         fetched in batches of 10. Returns companyName reliably on paid plans.
      3. FMP /stable/stock-list — broad fallback, ~30k symbols, one API call.
      4. Empty string — if all sources fail, name is left blank (not an error).
    """
    global _NAME_CACHE

    # Seed cache from static table on first call
    if not _NAME_CACHE:
        try:
            from data.company_names import NAMES as _STATIC
            _NAME_CACHE.update(_STATIC)
            log.debug("Loaded %d company names from static table", len(_NAME_CACHE))
        except ImportError:
            log.debug("Static name table not found — using API only")

    # Which tickers are still missing?
    missing = [t for t in tickers if t not in _NAME_CACHE]

    if missing:
        log.debug("%d tickers missing from static table — fetching from FMP profile", len(missing))
        # Try /stable/profile in batches of 10
        for i in range(0, len(missing), 10):
            batch = missing[i: i + 10]
            try:
                resp = _SESSION.get(
                    f"{BASE}/profile",
                    params={"symbol": ",".join(batch), "apikey": config.FMP_API_KEY},
                    timeout=10,
                )
                if resp.status_code in _PLAN_RESTRICTED:
                    log.debug("profile: plan restriction — skipping batch %s", batch)
                    continue
                resp.raise_for_status()
                profiles = resp.json()
                if isinstance(profiles, list):
                    for p in profiles:
                        sym  = (p.get("symbol") or "").strip()
                        name = (p.get("companyName") or p.get("name") or "").strip()
                        if sym and name:
                            _NAME_CACHE[sym] = name
            except Exception as e:
                log.debug("profile batch failed %s: %s", batch, e)

        # Any still missing? Try stock-list as broad fallback (one call)
        still_missing = [t for t in missing if t not in _NAME_CACHE]
        if still_missing:
            try:
                resp = _SESSION.get(
                    f"{BASE}/stock-list",
                    params={"apikey": config.FMP_API_KEY},
                    timeout=20,
                )
                if resp.ok:
                    for item in resp.json():
                        sym  = (item.get("symbol") or "").strip()
                        name = (item.get("name") or item.get("companyName") or "").strip()
                        if sym and name:
                            _NAME_CACHE[sym] = name
                    log.debug("stock-list loaded %d total names", len(_NAME_CACHE))
            except Exception as e:
                log.debug("stock-list fetch failed: %s", e)

    resolved = sum(1 for t in tickers if _NAME_CACHE.get(t))
    log.info("Company names: %d/%d resolved", resolved, len(tickers))
    return {t: _NAME_CACHE.get(t, "") for t in tickers}
