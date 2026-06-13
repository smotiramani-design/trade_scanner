"""
signals/greeks.py — ENH-20: Greeks-aware entry sizing.

Fetches the option chain for a ticker via Yahoo Finance (yfinance) and
identifies the highest-gamma strike nearest to the current price.

Data source: yfinance Ticker.option_chain(expiry)
  → chain.calls / chain.puts — pandas DataFrames
  → columns: strike, bid, ask, lastPrice, volume, openInterest,
             impliedVolatility, inTheMoney, contractSize, currency
  → NOTE: yfinance does NOT provide gamma — we compute it from Black-Scholes
          using the impliedVolatility column it does provide.
  → No API key required. Free. Same yfinance dependency already in requirements.txt.

High gamma at a strike means:
  - Market makers are hedging heavily near that level
  - Price tends to pin or be repelled by the strike (gamma pinning)
  - Large moves through high-gamma strikes are magnified (gamma squeeze)

Position sizing adjustment:
  If entry price is within GAMMA_PIN_BAND_PCT of a high-gamma strike:
    → REDUCE position size (gamma pinning may stall the move)
  If entry breaks through a high-gamma strike with strong signal:
    → INCREASE position size (gamma squeeze acceleration)

Output stored on TickerAnalysis.gamma_data and used in trade_engine.py
to scale the position size up or down.

No additional dependencies required — yfinance is already installed.
GREEKS_ENABLED=true in .env to activate.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

GAMMA_PIN_BAND_PCT  = 1.0    # % distance from entry to count as "near" a pin strike
GAMMA_SQUEEZE_MULT  = 1.25   # multiply position size by this near high-gamma breakout
GAMMA_PIN_MULT      = 0.75   # multiply position size by this when pinned
HIGH_OI_THRESHOLD   = 1000   # minimum open interest to consider a strike "significant"
RISK_FREE_RATE      = 0.045  # ~5y treasury — gamma is fairly insensitive to this


@dataclass
class GammaData:
    """Option chain Greeks summary for a ticker."""
    ticker:           str
    price:            float
    nearest_strike:   Optional[float]   # closest strike to current price
    nearest_gamma:    Optional[float]   # gamma at nearest strike
    nearest_oi:       Optional[int]     # open interest at nearest strike
    max_gamma_strike: Optional[float]   # strike with highest gamma (all strikes)
    max_gamma_value:  Optional[float]
    pin_risk:         bool = False       # True if price is near high-gamma strike
    squeeze_setup:    bool = False       # True if signal breaks through gamma level
    size_multiplier:  float = 1.0        # position size adjustment
    detail:           str = ""           # human-readable summary


def _bs_gamma(S: float, K: float, T: float, sigma: float, r: float = RISK_FREE_RATE) -> float:
    """
    Black-Scholes gamma: N'(d1) / (S·σ·√T).
    Same formula for calls and puts (gamma is direction-agnostic).
    Returns 0.0 on degenerate inputs.
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    try:
        sqrt_T = math.sqrt(T)
        d1     = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt_T)
        pdf    = math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi)
        return pdf / (S * sigma * sqrt_T)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _nearest_expiry(tk) -> Optional[str]:
    """
    Return the nearest available expiry from yfinance that is at least 1 day away.
    Prefers the closest weekly expiry — typically the coming Friday.
    Returns None if no expiries available.
    """
    try:
        expiries = tk.options   # tuple of 'YYYY-MM-DD' strings, sorted ascending
        if not expiries:
            return None
        today = date.today().isoformat()
        # Skip same-day expiry (0 DTE) — gamma is extreme and unreliable
        future = [e for e in expiries if e > today]
        return future[0] if future else expiries[-1]
    except Exception as e:
        log.debug("Could not fetch expiry list: %s", e)
        return None


def fetch_option_chain(ticker: str) -> Optional[Dict]:
    """
    Fetch option chain via Yahoo Finance (yfinance).
    Returns dict {calls: DataFrame, puts: DataFrame, expiry: str} or None on failure.

    yfinance returns pandas DataFrames with columns:
      strike, bid, ask, lastPrice, volume, openInterest,
      impliedVolatility, inTheMoney, contractSize, currency
    Gamma is NOT included — callers must compute via _bs_gamma.
    """
    try:
        import yfinance as yf
        tk     = yf.Ticker(ticker)
        expiry = _nearest_expiry(tk)
        if not expiry:
            log.debug("%s: no option expiries available", ticker)
            return None
        chain = tk.option_chain(expiry)
        log.debug("%s: option chain fetched (expiry %s, %d calls, %d puts)",
                  ticker, expiry, len(chain.calls), len(chain.puts))
        return {"calls": chain.calls, "puts": chain.puts, "expiry": expiry}
    except Exception as e:
        log.debug("Options chain fetch failed %s: %s", ticker, e)
        return None


def _find_high_gamma_strikes(
    chain_data:      Dict,
    price:           float,
    price_range_pct: float = 5.0,
) -> List[Tuple[float, float, int]]:
    """
    Compute Black-Scholes gamma per strike (yfinance does not provide it),
    filter to price range and min OI, sort by gamma×OI desc.
    Returns list of (strike, gamma, open_interest).
    """
    expiry_str = chain_data.get("expiry")
    if not expiry_str:
        return []
    try:
        expiry_dt   = datetime.strptime(expiry_str, "%Y-%m-%d").date()
        days_to_exp = max(1, (expiry_dt - date.today()).days)
        T           = days_to_exp / 365.0
    except Exception as e:
        log.debug("Could not parse expiry %s: %s", expiry_str, e)
        return []

    results = []
    lo = price * (1 - price_range_pct / 100)
    hi = price * (1 + price_range_pct / 100)

    for df in (chain_data.get("calls"), chain_data.get("puts")):
        if df is None or df.empty:
            continue
        if "impliedVolatility" not in df.columns:
            continue
        mask   = (df["strike"] >= lo) & (df["strike"] <= hi)
        nearby = df[mask].dropna(subset=["impliedVolatility"]).copy()

        for _, row in nearby.iterrows():
            strike = float(row["strike"])
            iv     = float(row["impliedVolatility"])
            oi     = int(row.get("openInterest") or 0)
            if iv <= 0 or oi < HIGH_OI_THRESHOLD:
                continue
            gamma = _bs_gamma(price, strike, T, iv)
            if gamma > 0:
                results.append((strike, gamma, oi))

    results.sort(key=lambda x: x[1] * x[2], reverse=True)   # gamma × OI
    return results


def analyze_greeks(
    ticker:     str,
    price:      float,
    net_score:  int,
    direction:  str,           # "buy" | "sell"
) -> GammaData:
    """
    Fetch options data and determine position size adjustment.

    Returns GammaData with:
      pin_risk=True     → reduce size (price likely to stall)
      squeeze_setup=True → increase size (gamma acceleration if signal fires)
      size_multiplier    → multiply standard position size by this value
    """
    if not price or price <= 0:
        return GammaData(ticker=ticker, price=price, nearest_strike=None,
                         nearest_gamma=None, nearest_oi=None,
                         max_gamma_strike=None, max_gamma_value=None,
                         detail="No price — Greeks skipped")

    # Fetch via yfinance — expiry selection handled inside fetch_option_chain
    chain = fetch_option_chain(ticker)

    if not chain:
        return GammaData(ticker=ticker, price=price, nearest_strike=None,
                         nearest_gamma=None, nearest_oi=None,
                         max_gamma_strike=None, max_gamma_value=None,
                         detail="Options data unavailable (plan restriction or no chain)")

    # Find high-gamma strikes (handles calls + puts DataFrames internally)
    gamma_strikes = _find_high_gamma_strikes(chain, price)

    if not gamma_strikes:
        return GammaData(ticker=ticker, price=price, nearest_strike=None,
                         nearest_gamma=None, nearest_oi=None,
                         max_gamma_strike=None, max_gamma_value=None,
                         size_multiplier=1.0,
                         detail="No significant gamma strikes near price")

    # Closest significant strike to current price
    nearest = min(gamma_strikes, key=lambda x: abs(x[0] - price))
    n_strike, n_gamma, n_oi = nearest

    # Max gamma strike
    max_gs = gamma_strikes[0]

    # Distance from price to nearest high-gamma strike
    dist_pct = abs(price - n_strike) / price * 100

    # ── Sizing logic ──────────────────────────────────────────────────────────
    pin_risk      = False
    squeeze_setup = False
    size_mult     = 1.0

    if dist_pct <= GAMMA_PIN_BAND_PCT:
        # Price is sitting on a high-gamma strike — gamma pinning risk
        pin_risk  = True
        size_mult = GAMMA_PIN_MULT
        detail    = (f"⚠ Gamma pin risk: ${n_strike:.2f} strike ({dist_pct:.1f}% away) "
                     f"γ={n_gamma:.4f} OI={n_oi:,} — size reduced {size_mult:.0%}")
    else:
        # Check if we're breaking through a significant gamma level
        breaking_above = direction == "buy"  and price > n_strike
        breaking_below = direction == "sell" and price < n_strike
        if (breaking_above or breaking_below) and abs(net_score) >= 4:
            squeeze_setup = True
            size_mult     = GAMMA_SQUEEZE_MULT
            detail        = (f"⚡ Gamma squeeze setup: breaking ${n_strike:.2f} strike "
                             f"γ={n_gamma:.4f} OI={n_oi:,} — size increased {size_mult:.0%}")
        else:
            detail = (f"Nearest strike: ${n_strike:.2f} ({dist_pct:.1f}% away) "
                      f"γ={n_gamma:.4f} OI={n_oi:,} — standard sizing")

    return GammaData(
        ticker           = ticker,
        price            = price,
        nearest_strike   = n_strike,
        nearest_gamma    = n_gamma,
        nearest_oi       = n_oi,
        max_gamma_strike = max_gs[0],
        max_gamma_value  = max_gs[1],
        pin_risk         = pin_risk,
        squeeze_setup    = squeeze_setup,
        size_multiplier  = size_mult,
        detail           = detail,
    )
