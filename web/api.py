"""
web/api.py — ENH-22: FastAPI backend for the scanner web dashboard.

Endpoints:
  GET  /api/health               — liveness check
  GET  /api/scan                 — trigger a scan, return results as JSON
  GET  /api/results/latest       — latest scan results from disk
  GET  /api/results              — all saved scan result files (index)
  GET  /api/watchlist            — current watchlist tickers + metadata
  GET  /api/positions            — current Alpaca paper positions + P&L
  GET  /api/performance          — P&L tracker summary
  GET  /api/backtest/results     — list of backtest CSV files
  POST /api/backtest/run         — trigger a quick backtest (background)
  GET  /api/signals/{ticker}     — run signals for a single ticker on-demand

Run locally:
  pip install fastapi uvicorn
  cd intraday_scanner
  uvicorn web.api:app --reload --port 8000

Then open: http://localhost:8000
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse, JSONResponse
except ImportError:
    raise ImportError("Run: pip install fastapi uvicorn")

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import config

log = logging.getLogger(__name__)

app = FastAPI(
    title="Intraday Trading Signal Scanner",
    description="Real-time market signal scanner with Alpaca paper trading",
    version="1.0.0",
)

# Allow React dev server on port 3000 to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_DIR  = config.OUTPUT_DIR
_scan_cache: Optional[Dict] = None   # in-memory cache of last scan


# ── Helper serialisers ────────────────────────────────────────────────────────

def _serialise_ta(ta) -> Dict:
    """Convert TickerAnalysis to JSON-safe dict."""
    sigs = [
        {"name": s.name, "bias": s.bias.value, "label": s.label, "detail": s.detail}
        for s in ta.signals
    ]
    fib = None
    if ta.fib:
        f = ta.fib
        fib = {
            "direction":   getattr(f, "direction",   None),
            "anchor_high": getattr(f, "anchor_high", None),
            "anchor_low":  getattr(f, "anchor_low",  None),
            "entry_price": getattr(f, "entry_price", None),
            "stop_loss":   getattr(f, "stop_loss",   None),
            "target_1":    getattr(f, "target_1",    None),
            "target_2":    getattr(f, "target_2",    None),
            "target_3":    getattr(f, "target_3",    None),
            "rr_t1":       getattr(f, "rr_t1",       None),
        }
    return {
        "ticker":        ta.ticker,
        "company_name":  ta.company_name,
        "price":         ta.price,
        "chg_pct":       ta.chg_pct,
        "volume":        ta.volume,
        "bars":          ta.bars,
        "mode":          ta.mode,
        "net_score":     ta.net_score,
        "bull_count":    ta.bull_count,
        "bear_count":    ta.bear_count,
        "verdict":       ta.verdict,
        "signals":       sigs,
        "fib":           fib,
        "atr_stop":      getattr(ta, "atr_stop",      None),
        "mtf_aligned":   getattr(ta, "mtf_aligned",   True),
        "mtf_detail":    getattr(ta, "mtf_detail",    ""),
        "earnings_soon": getattr(ta, "earnings_soon", False),
    }


def _serialise_cs(cs) -> Dict:
    """Convert ConvictionScore to JSON-safe dict."""
    return {
        "ticker":          cs.ticker,
        "raw_score":       cs.raw_score,
        "weighted_score":  cs.weighted_score,
        "conviction_pct":  cs.conviction_pct,
        "direction":       cs.direction,
        "grade":           cs.grade,
        "analysis":        cs.analysis,
        "key_signals":     cs.key_signals,
        "conflicting":     cs.conflicting,
    }


# ── Background scan runner ────────────────────────────────────────────────────

_scan_running = False

def _run_scan_bg(universe: str, max_tickers: int) -> None:
    """Background task: run full scan and cache results."""
    global _scan_cache, _scan_running
    _scan_running = True
    try:
        from scanner import scan, resolve_universe
        from signals.conviction import score_conviction

        tickers = resolve_universe(universe, max_tickers)
        results = scan(tickers)

        bulls, bears = [], []
        all_serialised = []
        for ta in results:
            cs = score_conviction(ta)
            item = {"analysis": _serialise_ta(ta), "conviction": _serialise_cs(cs)}
            all_serialised.append(item)
            if ta.net_score > 0:
                bulls.append(item)
            elif ta.net_score < 0:
                bears.append(item)

        _scan_cache = {
            "timestamp":  datetime.now().isoformat(),
            "universe":   universe,
            "total":      len(results),
            "bulls":      bulls[:10],
            "bears":      bears[-10:],
            "all_results": all_serialised,
        }
        log.info("Background scan complete: %d tickers", len(results))
    except Exception as e:
        log.error("Background scan failed: %s", e)
        _scan_cache = {"error": str(e), "timestamp": datetime.now().isoformat()}
    finally:
        _scan_running = False


# ── API routes ────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "scan_running": _scan_running,
        "alpaca_enabled": config.ALPACA_ENABLED,
        "trade_enabled": config.TRADE_ENABLED,
    }


@app.post("/api/scan")
def trigger_scan(
    background: BackgroundTasks,
    universe:    str = Query(default="watchlist"),
    max_tickers: int = Query(default=0),
):
    """Trigger a background scan. Poll /api/results/latest for results."""
    global _scan_running
    if _scan_running:
        return {"status": "already_running", "message": "Scan already in progress"}
    background.add_task(_run_scan_bg, universe, max_tickers)
    return {"status": "started", "universe": universe, "max_tickers": max_tickers}


@app.get("/api/results/latest")
def latest_results(top_n: int = Query(default=5)):
    """Return cached scan results or latest file from disk."""
    if _scan_cache:
        cache = dict(_scan_cache)
        cache["bulls"] = cache.get("bulls", [])[:top_n]
        cache["bears"] = cache.get("bears", [])[-top_n:]
        cache["source"] = "cache"
        return cache

    # Fall back to most recent output file
    files = sorted(OUTPUT_DIR.glob("scan_*.json"), reverse=True)
    if files:
        with open(files[0]) as f:
            data = json.load(f)
        data["source"] = "file"
        return data

    return {"status": "no_results", "message": "Run a scan first via POST /api/scan"}


@app.get("/api/results")
def list_results():
    """List all saved scan result files."""
    files = sorted(OUTPUT_DIR.glob("scan_*.json"), reverse=True)
    return [{"filename": f.name, "size_kb": round(f.stat().st_size / 1024, 1),
             "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()}
            for f in files[:20]]


@app.get("/api/watchlist")
def get_watchlist():
    """Return watchlist tiers and metadata."""
    from universes import (WATCHLIST_TIER1, WATCHLIST_TIER2, WATCHLIST_TIER3,
                           WATCHLIST_EXCLUDE, NO_FIB_TICKERS)
    return {
        "tier1":   WATCHLIST_TIER1,
        "tier2":   WATCHLIST_TIER2,
        "tier3":   WATCHLIST_TIER3,
        "exclude": WATCHLIST_EXCLUDE,
        "no_fib":  NO_FIB_TICKERS,
        "total":   len(WATCHLIST_TIER1) + len(WATCHLIST_TIER2) + len(WATCHLIST_TIER3),
    }


@app.get("/api/positions")
def get_positions():
    """Return current Alpaca paper positions with live P&L."""
    if not config.ALPACA_ENABLED:
        return {"error": "Alpaca not configured", "positions": []}
    try:
        from trading.alpaca_client import get_client
        client = get_client()
        acct   = client.get_account()
        positions = client.get_positions()
        return {
            "account": {
                "equity":       acct.equity       if acct else None,
                "cash":         acct.cash         if acct else None,
                "buying_power": acct.buying_power if acct else None,
                "paper":        acct.paper        if acct else True,
            },
            "positions": [
                {
                    "symbol":        p.symbol,
                    "qty":           p.qty,
                    "side":          p.side,
                    "avg_entry":     p.avg_entry,
                    "current_price": p.current_price,
                    "market_value":  p.market_value,
                    "unrealized_pl": p.unrealized_pl,
                    "unrealized_pct":round(p.unrealized_pct, 2),
                }
                for p in positions
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/performance")
def get_performance():
    """Return P&L tracker summary from trade ledger."""
    try:
        from trading.pnl_tracker import get_performance_summary
        ps = get_performance_summary()
        if ps.total_trades == 0:
            return {"total_trades": 0, "message": "No closed trades yet"}
        return {
            "total_trades":   ps.total_trades,
            "wins":           ps.wins,
            "losses":         ps.losses,
            "win_rate":       ps.win_rate,
            "avg_r":          ps.avg_r,
            "expectancy":     ps.expectancy,
            "total_pnl_usd":  ps.total_pnl_usd,
            "avg_win_usd":    ps.avg_win_usd,
            "avg_loss_usd":   ps.avg_loss_usd,
            "best_trade":     {"ticker": ps.best_trade.ticker,  "pnl": ps.best_trade.pnl_usd}  if ps.best_trade  else None,
            "worst_trade":    {"ticker": ps.worst_trade.ticker, "pnl": ps.worst_trade.pnl_usd} if ps.worst_trade else None,
            "current_streak": ps.current_streak,
            "streak_type":    ps.streak_type,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/signals/{ticker}")
def get_signals_for_ticker(ticker: str, hourly: bool = Query(default=False)):
    """Run signals for a single ticker on demand and return results."""
    try:
        from data.yahoo_client import get_bars
        from signals import run_all, SIG_NAMES
        from signals.conviction import score_conviction
        from signals.base import TickerAnalysis
        from signals.fibonacci import compute_fibonacci

        bars = get_bars(ticker.upper(), market_open=hourly)
        if len(bars) < 30:
            raise HTTPException(status_code=404, detail=f"Insufficient bars for {ticker}")

        sigs = run_all(bars, ticker=ticker.upper())
        ta   = TickerAnalysis(
            ticker=ticker.upper(), price=bars[-1].close,
            chg_pct=0, volume=bars[-1].volume, bars=len(bars),
            mode="Hourly" if hourly else "Daily",
            signals=sigs,
        )
        ta.fib = compute_fibonacci(ticker, bars, bars[-1].close, ta.net_score)
        cs     = score_conviction(ta)

        return {
            "ticker":     ticker.upper(),
            "price":      bars[-1].close,
            "net_score":  ta.net_score,
            "conviction": _serialise_cs(cs),
            "signals":    [{"name": n, "bias": s.bias.value, "label": s.label, "detail": s.detail}
                           for n, s in zip(SIG_NAMES, sigs)],
            "fib":        _serialise_ta(ta)["fib"],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/backtest/results")
def list_backtest_results():
    """List all backtest CSV files."""
    files = sorted(OUTPUT_DIR.glob("backtest_*.csv"), reverse=True)
    return [{"filename": f.name, "size_kb": round(f.stat().st_size / 1024, 1),
             "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()}
            for f in files[:20]]


# ── Serve React frontend (production build) ───────────────────────────────────

FRONTEND_DIR = Path(__file__).parent / "frontend" / "dist"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

    @app.get("/")
    def root():
        return FileResponse(str(FRONTEND_DIR / "index.html"))
