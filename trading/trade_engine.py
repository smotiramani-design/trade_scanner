"""
trading/trade_engine.py — Trade decision engine.

Takes scan results + conviction scores and decides:
  1. Which tickers qualify for a trade (score + conviction thresholds)
  2. What direction (long / short)
  3. Position sizing (% of portfolio, capped at max USD)
  4. Entry price (limit or market)
  5. Stop loss and take-profit levels (from Fibonacci or fallback %)

Decision rules
──────────────
Entry criteria (ALL must pass):
  • Ticker on backtest-validated WATCHLIST (15 Nasdaq tickers with proven edge)
  • Ticker NOT on WATCHLIST_EXCLUDE (tickers with zero model edge)
  • Net signal score  ≥ TRADE_MIN_SCORE (default 4)
  • Conviction %      ≥ TRADE_MIN_CONVICTION (default 60%)
  • Open positions    <  TRADE_MAX_POSITIONS
  • Not already in a position for that ticker
  • Asset is tradable on Alpaca

Position sizing:
  size_usd = min(portfolio_value × TRADE_POSITION_SIZE_PCT/100,
                 TRADE_MAX_POSITION_USD)
  qty      = size_usd / entry_price

Stop / take-profit:
  Prefer Fibonacci entry/stop/target_1 levels when available.
  Fallback: entry ± TRADE_STOP_LOSS_PCT / TRADE_TAKE_PROFIT_PCT %

Direction:
  TRADE_DIRECTION=long_only  → only buy bullish picks
  TRADE_DIRECTION=short_only → only sell bearish picks
  TRADE_DIRECTION=both       → both (default)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import config
from signals.base import TickerAnalysis
from signals.conviction import ConvictionScore
from trading.alpaca_client import AlpacaClient, OrderResult, get_client
from trading.position_monitor import record_new_position
from universes import is_watchlist_ticker, is_excluded_ticker, WATCHLIST, NO_FIB_TICKERS

log = logging.getLogger(__name__)


@dataclass
class TradeDecision:
    ticker:       str
    action:       str           # "buy" | "sell" | "skip"
    reason:       str
    qty:          float = 0.0
    entry_price:  Optional[float] = None
    stop_loss:    Optional[float] = None
    take_profit:  Optional[float] = None
    size_usd:     float = 0.0
    order_result: Optional[OrderResult] = None

    @property
    def executed(self) -> bool:
        return self.order_result is not None and self.order_result.success


def _calc_entry_stop_tp(
    ta: TickerAnalysis,
    cs: ConvictionScore,
    direction: str,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Return (entry_price, stop_loss, take_profit).

    Level selection strategy (backtested across 101 Nasdaq tickers):
      Fibonacci ON  — tickers where Fib stop/TP improves expectancy
                      (slower range-bound tech: APP, ZS, CTSH, AMD, SNDK…)
      Fixed %       — tickers where Fib stop is too tight and gets gapped through
                      (fast momentum stocks: NFLX, QCOM, INSM, TTWO, MNST…)

    The NO_FIB_TICKERS set in universes.py is the authoritative list.
    Any ticker not in that set uses Fibonacci when available.
    """
    price = ta.price
    if not price or price <= 0:
        return None, None, None

    # ── Ticker-aware level selection ──────────────────────────────────────────
    use_fib = ta.ticker not in NO_FIB_TICKERS

    fib = ta.fib
    if use_fib and fib and fib.entry_price and fib.stop_loss and fib.target_1:
        entry = fib.entry_price
        stop  = fib.stop_loss
        tp    = fib.target_1
        log.debug("%s: Fibonacci levels  entry=$%.2f stop=$%.2f tp=$%.2f",
                  ta.ticker, entry, stop, tp)
    else:
        # Fixed % from current price (validated config: stop=1.5%, tp=4.5%)
        entry = price
        if direction == "buy":
            stop = round(price * (1 - config.TRADE_STOP_LOSS_PCT / 100), 2)
            tp   = round(price * (1 + config.TRADE_TAKE_PROFIT_PCT / 100), 2)
        else:
            stop = round(price * (1 + config.TRADE_STOP_LOSS_PCT / 100), 2)
            tp   = round(price * (1 - config.TRADE_TAKE_PROFIT_PCT / 100), 2)
        reason = "no-fib ticker" if ta.ticker in NO_FIB_TICKERS else "no Fib levels"
        log.debug("%s: fixed %% levels (%s)  entry=$%.2f stop=$%.2f tp=$%.2f",
                  ta.ticker, reason, entry, stop, tp)

    # ENH-10: ATR stop override — use ATR stop when it gives MORE room than fixed stop
    # (ATR adapts to actual volatility; never let Fib/fixed stop be tighter than ATR)
    atr_stop = getattr(ta, "atr_stop", None)
    if atr_stop and stop:
        if direction == "buy" and atr_stop < stop:
            # ATR says stop should be wider — use it to avoid premature stops
            log.debug("%s: ATR stop override $%.2f → $%.2f (wider)", ta.ticker, stop, atr_stop)
            stop = atr_stop
        elif direction == "sell" and atr_stop > stop:
            log.debug("%s: ATR stop override $%.2f → $%.2f (wider)", ta.ticker, stop, atr_stop)
            stop = atr_stop

    return entry, stop, tp


def _calc_qty(
    entry_price:   float,
    account_value: float,
    gamma_mult:    float = 1.0,   # ENH-20: Greeks-aware size multiplier (0.75–1.25)
) -> int:
    """
    Calculate whole-share quantity — no fractional shares.
    gamma_mult scales position size based on gamma pin/squeeze analysis:
      0.75 = near gamma pin (reduce size — price may stall)
      1.00 = standard
      1.25 = gamma squeeze setup (increase size — acceleration expected)
    """
    size_usd = min(
        account_value * config.TRADE_POSITION_SIZE_PCT / 100,
        config.TRADE_MAX_POSITION_USD,
    )
    size_usd = round(size_usd * gamma_mult, 2)   # apply Greeks adjustment
    if entry_price <= 0:
        return 0
    return int(size_usd // entry_price)   # floor → whole shares only


def _should_enter(
    ta: TickerAnalysis,
    cs: ConvictionScore,
    direction: str,
    client: AlpacaClient,
) -> Tuple[bool, str]:
    """
    Returns (should_trade, reason).
    Checks all entry criteria sequentially.
    """
    # 1. Watchlist gate — only trade backtest-validated tickers
    if is_excluded_ticker(ta.ticker):
        return False, f"{ta.ticker} on exclude list — zero model edge in backtest"
    if config.TRADE_WATCHLIST_ONLY and not is_watchlist_ticker(ta.ticker):
        return False, f"{ta.ticker} not on validated watchlist (TRADE_WATCHLIST_ONLY=true)"

    # 2. Score threshold
    abs_score = abs(ta.net_score)
    if abs_score < config.TRADE_MIN_SCORE:
        return False, f"Score {ta.net_score:+d} below minimum {config.TRADE_MIN_SCORE}"

    # 3. Conviction threshold
    if cs.conviction_pct < config.TRADE_MIN_CONVICTION:
        return False, f"Conviction {cs.conviction_pct:.1f}% below minimum {config.TRADE_MIN_CONVICTION}%"

    # 4. Direction filter
    dir_cfg = config.TRADE_DIRECTION
    if dir_cfg == "long_only" and direction != "buy":
        return False, "TRADE_DIRECTION=long_only — skipping short signal"
    if dir_cfg == "short_only" and direction != "sell":
        return False, "TRADE_DIRECTION=short_only — skipping long signal"

    # 5. Max positions
    if client.ready and client.position_count() >= config.TRADE_MAX_POSITIONS:
        return False, f"Max positions ({config.TRADE_MAX_POSITIONS}) reached"

    # 6. Already in position
    if client.ready and client.has_position(ta.ticker):
        return False, f"Already in position for {ta.ticker}"

    # 7. Price validity
    if not ta.price or ta.price <= 0:
        return False, "No valid price available"

    return True, "All entry criteria passed"


def evaluate_and_trade(
    picks:       List[Tuple[TickerAnalysis, ConvictionScore]],
    direction:   str,            # "buy" | "sell"
    account_value: float,
    client:      Optional[AlpacaClient] = None,
    dry_run:     bool = False,
    extended_hours: bool = False,  # ENH-07/08: True for pre/after-market sessions
) -> List[TradeDecision]:
    """
    Evaluate top picks and place orders for qualifying setups.

    Args:
        picks:         list of (TickerAnalysis, ConvictionScore) sorted by conviction
        direction:     "buy" for bullish picks, "sell" for bearish
        account_value: current portfolio value for position sizing
        client:        AlpacaClient (uses singleton if None)
        dry_run:       if True, evaluate but don't submit orders

    Returns:
        list of TradeDecision for all evaluated tickers
    """
    if client is None:
        client = get_client()

    decisions: List[TradeDecision] = []

    for ta, cs in picks:
        should, reason = _should_enter(ta, cs, direction, client)

        if not should:
            decisions.append(TradeDecision(
                ticker=ta.ticker, action="skip", reason=reason
            ))
            log.debug("SKIP %s: %s", ta.ticker, reason)
            continue

        entry, stop, tp = _calc_entry_stop_tp(ta, cs, direction)
        if not entry:
            decisions.append(TradeDecision(
                ticker=ta.ticker, action="skip",
                reason="Could not calculate entry price"
            ))
            continue

        # ENH-20: extract gamma size multiplier if available
        gamma_mult = 1.0
        gd = getattr(ta, "gamma_data", None)
        if gd and hasattr(gd, "size_multiplier"):
            gamma_mult = gd.size_multiplier
            if gamma_mult != 1.0:
                log.info("Greeks sizing %s: multiplier=%.2f (%s)",
                         ta.ticker, gamma_mult, gd.detail[:60])

        qty      = _calc_qty(entry, account_value, gamma_mult)
        if qty == 0:
            decisions.append(TradeDecision(
                ticker=ta.ticker, action="skip",
                reason=f"Position budget (${config.TRADE_MAX_POSITION_USD:.0f}) "
                       f"too small to buy 1 share at ${entry:.2f}"
            ))
            continue
        size_usd = qty * entry

        # Apply limit price offset for limit orders
        limit_price: Optional[float] = None
        if config.TRADE_ORDER_TYPE == "limit":
            offset = config.TRADE_LIMIT_OFFSET_PCT / 100
            if direction == "buy":
                limit_price = round(entry * (1 + offset), 2)   # slightly above for fills
            else:
                limit_price = round(entry * (1 - offset), 2)   # slightly below for fills

        decision = TradeDecision(
            ticker=ta.ticker, action=direction,
            reason=reason,
            qty=qty, entry_price=entry,
            stop_loss=stop, take_profit=tp,
            size_usd=size_usd,
        )

        if dry_run:
            log.info(
                "DRY RUN %s %s: entry=$%.2f stop=$%.2f tp=$%.2f qty=%.4f (~$%.0f) "
                "conviction=%.1f%% score=%+d",
                direction.upper(), ta.ticker, entry, stop or 0, tp or 0,
                qty, size_usd, cs.conviction_pct, ta.net_score,
            )
        else:
            log.info(
                "TRADE %s %s: entry=$%.2f stop=$%.2f tp=$%.2f qty=%.4f (~$%.0f) "
                "conviction=%.1f%% score=%+d",
                direction.upper(), ta.ticker, entry, stop or 0, tp or 0,
                qty, size_usd, cs.conviction_pct, ta.net_score,
            )

            if direction == "buy":
                result = client.buy(
                    symbol=ta.ticker, qty=qty,
                    limit_price=limit_price,
                    stop_loss=stop, take_profit=tp,
                    extended_hours=extended_hours,
                )
            else:
                result = client.sell(
                    symbol=ta.ticker, qty=qty,
                    limit_price=limit_price,
                    stop_loss=stop, take_profit=tp,
                    extended_hours=extended_hours,
                )
            decision.order_result = result

            # Record position metadata for inter-scan stop/TP monitoring
            if result.success and stop and tp:
                record_new_position(
                    ticker=ta.ticker,
                    side=direction,
                    entry_price=entry,
                    stop_loss=stop,
                    take_profit=tp,
                    qty=int(qty),
                    conviction=cs.conviction_pct,
                    score=ta.net_score,
                )

        decisions.append(decision)

    return decisions


def run_trade_session(
    bulls:   List[Tuple[TickerAnalysis, ConvictionScore]],
    bears:   List[Tuple[TickerAnalysis, ConvictionScore]],
    dry_run: bool = False,
) -> Tuple[List[TradeDecision], List[TradeDecision], Optional[dict]]:
    """
    Full trade session: evaluate + execute bull and bear picks.

    Detects current market session and sets extended_hours=True automatically
    for pre-market (4–9:30 AM ET) and after-hours (4–8 PM ET) sessions.
    Extended-hours orders are limit-only with no bracket legs per Alpaca rules.

    Returns:
        (bull_decisions, bear_decisions, account_summary)
    """
    client = get_client()

    if not config.TRADE_ENABLED and not dry_run:
        log.info("TRADE_ENABLED=false — running in dry-run mode")
        dry_run = True

    # Detect if we are in an extended-hours session (ENH-07/08)
    from data.fmp_client import get_market_session, MarketSession
    _session = get_market_session()
    extended_hours = _session in (MarketSession.PREMARKET, MarketSession.AFTERHOURS)
    if extended_hours:
        log.info("Extended-hours session (%s) — bracket orders disabled, limit-only",
                 _session.value)

    # Get account value for position sizing
    account_value = config.TRADE_MAX_POSITION_USD * config.TRADE_MAX_POSITIONS
    account_summary = None
    if client.ready:
        acct = client.get_account()
        if acct:
            account_value   = acct.portfolio_value
            account_summary = {
                "equity":       acct.equity,
                "cash":         acct.cash,
                "buying_power": acct.buying_power,
                "paper":        acct.paper,
                "status":       acct.status,
            }
            log.info(
                "Account: equity=$%.2f cash=$%.2f buying_power=$%.2f [%s]",
                acct.equity, acct.cash, acct.buying_power,
                "PAPER" if acct.paper else "LIVE",
            )

    bull_decisions = evaluate_and_trade(bulls, "buy",  account_value, client, dry_run, extended_hours)
    bear_decisions = evaluate_and_trade(bears, "sell", account_value, client, dry_run, extended_hours)

    executed_buys  = sum(1 for d in bull_decisions if d.executed)
    executed_sells = sum(1 for d in bear_decisions if d.executed)
    skipped        = sum(1 for d in bull_decisions + bear_decisions if d.action == "skip")

    log.info(
        "Trade session complete: %d buys, %d sells, %d skipped%s",
        executed_buys, executed_sells, skipped,
        " [DRY RUN]" if dry_run else "",
    )

    return bull_decisions, bear_decisions, account_summary
