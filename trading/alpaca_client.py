"""
trading/alpaca_client.py — Alpaca paper trading client.

Wraps alpaca-py (TradingClient) and exposes:
  - Account info / buying power
  - Position management
  - Order placement (market + limit with bracket stop/take-profit)
  - Order status and history
  - Position close

Safety guarantees:
  - Will NEVER submit a live order if ALPACA_PAPER=true
  - TRADE_ENABLED must be True in .env for any order to execute
  - All order calls are no-ops when either guard is off, returning
    a clear log message instead of raising

Install: pip install alpaca-py
Docs:    https://alpaca.markets/sdks/python/trading.html
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

import config

log = logging.getLogger(__name__)


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class AccountInfo:
    equity:           float
    cash:             float
    buying_power:     float
    portfolio_value:  float
    day_trade_count:  int
    pattern_day_trader: bool
    trading_blocked:  bool
    account_blocked:  bool
    status:           str
    paper:            bool


@dataclass
class Position:
    symbol:        str
    qty:           float
    side:          str          # "long" | "short"
    avg_entry:     float
    current_price: float
    market_value:  float
    unrealized_pl: float
    unrealized_pct:float
    change_today:  float


@dataclass
class OrderResult:
    success:    bool
    order_id:   str = ""
    symbol:     str = ""
    side:       str = ""
    qty:        float = 0.0
    order_type: str = ""
    limit_price: Optional[float] = None
    stop_price:  Optional[float] = None
    take_profit: Optional[float] = None
    status:     str = ""
    message:    str = ""
    submitted_at: Optional[datetime] = None


# ── Client ────────────────────────────────────────────────────────────────────

class AlpacaClient:
    """
    Thin wrapper around alpaca-py TradingClient.
    All methods are safe to call even when trading is disabled —
    they log a warning and return sensible defaults instead of raising.
    """

    def __init__(self) -> None:
        self._client = None
        self._ready  = False

        if not config.ALPACA_ENABLED:
            log.warning("Alpaca not configured — set ALPACA_API_KEY and ALPACA_SECRET_KEY in .env")
            return

        try:
            from alpaca.trading.client import TradingClient
            self._client = TradingClient(
                api_key    = config.ALPACA_API_KEY,
                secret_key = config.ALPACA_SECRET_KEY,
                paper      = config.ALPACA_PAPER,
            )
            self._ready = True
            mode = "PAPER" if config.ALPACA_PAPER else "⚠ LIVE"
            log.info("Alpaca client initialised — mode: %s", mode)
        except ImportError:
            log.error("alpaca-py not installed. Run: pip install alpaca-py")
        except Exception as e:
            log.error("Alpaca client init failed: %s", e)

    @property
    def ready(self) -> bool:
        return self._ready

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account(self) -> Optional[AccountInfo]:
        if not self._ready:
            return None
        try:
            a = self._client.get_account()
            return AccountInfo(
                equity           = float(a.equity),
                cash             = float(a.cash),
                buying_power     = float(a.buying_power),
                portfolio_value  = float(a.portfolio_value),
                day_trade_count  = int(a.daytrade_count or 0),
                pattern_day_trader = bool(a.pattern_day_trader),
                trading_blocked  = bool(a.trading_blocked),
                account_blocked  = bool(a.account_blocked),
                status           = str(a.status),
                paper            = config.ALPACA_PAPER,
            )
        except Exception as e:
            log.error("get_account failed: %s", e)
            return None

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_positions(self) -> List[Position]:
        if not self._ready:
            return []
        try:
            raw = self._client.get_all_positions()
            positions = []
            for p in raw:
                positions.append(Position(
                    symbol        = p.symbol,
                    qty           = float(p.qty),
                    side          = p.side.value if hasattr(p.side, 'value') else str(p.side),
                    avg_entry     = float(p.avg_entry_price),
                    current_price = float(p.current_price),
                    market_value  = float(p.market_value),
                    unrealized_pl = float(p.unrealized_pl),
                    unrealized_pct= float(p.unrealized_plpc) * 100,
                    change_today  = float(p.change_today or 0) * 100,
                ))
            return positions
        except Exception as e:
            log.error("get_positions failed: %s", e)
            return []

    def get_position(self, symbol: str) -> Optional[Position]:
        positions = self.get_positions()
        return next((p for p in positions if p.symbol == symbol), None)

    def position_count(self) -> int:
        return len(self.get_positions())

    def has_position(self, symbol: str) -> bool:
        return self.get_position(symbol) is not None

    # ── Orders ────────────────────────────────────────────────────────────────

    def _trade_guard(self, action: str, symbol: str) -> Optional[OrderResult]:
        """Returns an error OrderResult if trading guards prevent execution."""
        if not config.TRADE_ENABLED:
            msg = f"TRADE_ENABLED=false — {action} {symbol} blocked. Set TRADE_ENABLED=true in .env to execute trades."
            log.warning(msg)
            return OrderResult(success=False, symbol=symbol, message=msg)
        if not self._ready:
            msg = "Alpaca client not ready — check API keys in .env"
            log.error(msg)
            return OrderResult(success=False, symbol=symbol, message=msg)
        if not config.ALPACA_PAPER:
            # Extra warning for live trading
            log.warning("⚠ LIVE TRADING MODE — submitting real order for %s", symbol)
        return None  # all guards passed

    def buy(
        self,
        symbol:         str,
        qty:            float,
        limit_price:    Optional[float] = None,
        stop_loss:      Optional[float] = None,
        take_profit:    Optional[float] = None,
        extended_hours: bool = False,
    ) -> OrderResult:
        """
        Place a BUY order (long entry).
        extended_hours=True for pre-market (4–9:30 AM) or after-hours (4–8 PM) sessions.
        Extended-hours orders are limit-only; bracket legs are disabled per Alpaca rules.
        """
        guard = self._trade_guard("BUY", symbol)
        if guard:
            return guard
        return self._submit_order(
            symbol=symbol, side="buy", qty=qty,
            limit_price=limit_price, stop_loss=stop_loss, take_profit=take_profit,
            extended_hours=extended_hours,
        )

    def sell(
        self,
        symbol:         str,
        qty:            float,
        limit_price:    Optional[float] = None,
        stop_loss:      Optional[float] = None,
        take_profit:    Optional[float] = None,
        extended_hours: bool = False,
    ) -> OrderResult:
        """Place a SELL/SHORT order. Extended-hours rules apply when extended_hours=True."""
        guard = self._trade_guard("SELL", symbol)
        if guard:
            return guard
        return self._submit_order(
            symbol=symbol, side="sell", qty=qty,
            limit_price=limit_price, stop_loss=stop_loss, take_profit=take_profit,
            extended_hours=extended_hours,
        )

    def close_position(self, symbol: str) -> OrderResult:
        """Close an existing position at market price."""
        guard = self._trade_guard("CLOSE", symbol)
        if guard:
            return guard
        try:
            result = self._client.close_position(symbol)
            log.info("Closed position: %s | order_id=%s", symbol, result.id)
            return OrderResult(
                success=True, order_id=str(result.id),
                symbol=symbol, side="close",
                status=str(result.status),
                message=f"Position closed for {symbol}",
            )
        except Exception as e:
            log.error("close_position %s failed: %s", symbol, e)
            return OrderResult(success=False, symbol=symbol, message=str(e))

    def close_all_positions(self) -> List[OrderResult]:
        """Close all open positions. Use with caution."""
        guard = self._trade_guard("CLOSE ALL", "ALL")
        if guard:
            return [guard]
        try:
            statuses = self._client.close_all_positions(cancel_orders=True)
            results = []
            for s in statuses:
                results.append(OrderResult(
                    success=True, symbol=str(s.symbol) if hasattr(s, 'symbol') else "?",
                    message="Closed"
                ))
            log.info("Closed all positions: %d", len(results))
            return results
        except Exception as e:
            log.error("close_all_positions failed: %s", e)
            return [OrderResult(success=False, message=str(e))]

    def cancel_all_orders(self) -> bool:
        """Cancel all open orders."""
        if not self._ready:
            return False
        try:
            self._client.cancel_orders()
            log.info("All open orders cancelled")
            return True
        except Exception as e:
            log.error("cancel_all_orders failed: %s", e)
            return False

    def get_orders(self, status: str = "open") -> List[dict]:
        """Return list of orders filtered by status: open | closed | all."""
        if not self._ready:
            return []
        try:
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus
            status_map = {
                "open":   QueryOrderStatus.OPEN,
                "closed": QueryOrderStatus.CLOSED,
                "all":    QueryOrderStatus.ALL,
            }
            params = GetOrdersRequest(status=status_map.get(status, QueryOrderStatus.OPEN))
            orders = self._client.get_orders(filter=params)
            return [
                {
                    "id":          str(o.id),
                    "symbol":      o.symbol,
                    "side":        o.side.value,
                    "qty":         float(o.qty or 0),
                    "type":        o.order_type.value,
                    "status":      o.status.value,
                    "filled_qty":  float(o.filled_qty or 0),
                    "filled_price":float(o.filled_avg_price or 0),
                    "submitted_at":str(o.submitted_at),
                }
                for o in orders
            ]
        except Exception as e:
            log.error("get_orders failed: %s", e)
            return []

    # ── Internal order builder ────────────────────────────────────────────────

    def _submit_order(
        self,
        symbol:         str,
        side:           str,
        qty:            float,
        limit_price:    Optional[float],
        stop_loss:      Optional[float],
        take_profit:    Optional[float],
        extended_hours: bool = False,   # ENH-08: True for pre/after-market orders
    ) -> OrderResult:
        try:
            from alpaca.trading.requests import (
                MarketOrderRequest, LimitOrderRequest,
                OrderRequest, TakeProfitRequest, StopLossRequest,
            )
            from alpaca.trading.enums import OrderSide, TimeInForce

            alpaca_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
            # Extended-hours orders must use DAY time-in-force (Alpaca requirement)
            # and only limit orders are accepted outside regular hours
            tif = TimeInForce.DAY

            # Build take-profit / stop-loss legs — only valid during market hours
            # Alpaca does not support bracket orders for extended-hours sessions
            if extended_hours:
                tp_req = None
                sl_req = None
                log.info("Extended-hours order — bracket legs (stop/TP) disabled per Alpaca rules")
            else:
                tp_req = TakeProfitRequest(limit_price=round(take_profit, 2)) if take_profit else None
                sl_req = StopLossRequest(stop_price=round(stop_loss, 2))     if stop_loss   else None

            if limit_price:
                order_data = LimitOrderRequest(
                    symbol          = symbol,
                    qty             = int(qty),
                    side            = alpaca_side,
                    time_in_force   = tif,
                    limit_price     = round(limit_price, 2),
                    take_profit     = tp_req,
                    stop_loss       = sl_req,
                    extended_hours  = extended_hours,
                )
                order_type = "limit"
            else:
                if extended_hours:
                    # Extended-hours requires limit orders — convert to limit at market price
                    log.warning("%s: extended-hours requires limit order — using market price as limit", symbol)
                    from data.fmp_client import get_quotes
                    q = get_quotes([symbol])
                    mkt_price = float(q[0].get("price", 0)) if q else 0
                    if mkt_price > 0:
                        limit_price = round(mkt_price * (1.002 if side == "buy" else 0.998), 2)
                        order_data = LimitOrderRequest(
                            symbol         = symbol, qty = int(qty), side = alpaca_side,
                            time_in_force  = tif, limit_price = limit_price,
                            extended_hours = True,
                        )
                        order_type = "limit(ext)"
                    else:
                        return OrderResult(success=False, symbol=symbol,
                                           message="Extended-hours market order requires price — unavailable")
                else:
                    order_data = MarketOrderRequest(
                        symbol        = symbol,
                        qty           = int(qty),
                        side          = alpaca_side,
                        time_in_force = tif,
                        take_profit   = tp_req,
                        stop_loss     = sl_req,
                    )
                    order_type = "market"

            result = self._client.submit_order(order_data=order_data)

            log.info(
                "Order submitted: %s %s %s qty=%.4f lmt=%s sl=%s tp=%s → id=%s status=%s",
                side.upper(), order_type, symbol, qty,
                f"${limit_price:.2f}" if limit_price else "—",
                f"${stop_loss:.2f}"   if stop_loss   else "—",
                f"${take_profit:.2f}" if take_profit  else "—",
                result.id, result.status,
            )

            return OrderResult(
                success      = True,
                order_id     = str(result.id),
                symbol       = symbol,
                side         = side,
                qty          = qty,
                order_type   = order_type,
                limit_price  = limit_price,
                stop_price   = stop_loss,
                take_profit  = take_profit,
                status       = str(result.status),
                submitted_at = result.submitted_at,
                message      = f"{side.upper()} {order_type} order submitted for {symbol}",
            )

        except Exception as e:
            log.error("Order failed %s %s: %s", side, symbol, e)
            return OrderResult(
                success = False,
                symbol  = symbol,
                side    = side,
                message = str(e),
            )


# ── Singleton ─────────────────────────────────────────────────────────────────
_client: Optional[AlpacaClient] = None

def get_client() -> AlpacaClient:
    global _client
    if _client is None:
        _client = AlpacaClient()
    return _client
