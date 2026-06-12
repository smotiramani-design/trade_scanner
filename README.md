# Intraday Trading Signal Scanner

A Python-based algorithmic market analysis platform that scans US equity universes, scores each ticker against a **10-signal conviction model**, projects Fibonacci price targets, executes paper trades via Alpaca, and delivers results through a terminal, HTML email, Excel workbook, and web dashboard.

> **Paper trading only.** All trading features default to Alpaca paper mode. Not financial advice.

---

## What it does

```
Universe (614 tickers)
    ↓
FMP real-time quotes + company names + earnings calendar
    ↓
Async OHLCV bars (40 concurrent workers — ~12s for 600 tickers)
    ↓
10-signal conviction model  →  Fibonacci projections  →  ATR stop
    ↓
Multi-timeframe confirmation (hourly × daily alignment)
    ↓
Top picks ranked by conviction %
    ↓
Alpaca paper trade execution (watchlist-gated, bracket orders)
    ↓
Email report + Excel workbook + Web dashboard + P&L tracking
```

---

## Signal model — 10 signals

| # | Signal | Weight | Description |
|---|--------|--------|-------------|
| 1 | **Candle pattern** | 1.5× | Engulfing, hammer, shooting star, doji, marubozu |
| 2 | **Volume** | 1.5× | Current bar vs 20-bar average — direction only on high volume |
| 3 | **SMA divergence** | 1.0× | % distance from 20-period SMA |
| 4 | **Gaps** | 1.0× | Open unfilled gaps above/below price (proximity-sorted) |
| 5 | **Stochastics** | 1.2× | %K/%D crossover + overbought/oversold zones |
| 6 | **CCI** | 1.2× | Commodity Channel Index trend strength |
| 7 | **Role Reversal** | 1.6× | Prior support/resistance acting as opposite level |
| 8 | **Rel. Strength** | 1.3× | Outperformance vs SPY over 5-bar + 10-bar windows |
| 9 | **VWAP** | 1.1× | Above/below VWAP with std deviation bands (hourly only) |
| 10 | **News sentiment** | 0.9× | FMP headline scoring — keyword-based, 48h window |

Max weighted score: **11.4**. Conviction % = weighted score / 11.4 × 100.
Grade: A+ ≥85% · A ≥70% · B ≥55% · C ≥40% · D <40%

**Multi-timeframe conflict** (ENH-16): when hourly and daily signals disagree, conviction is reduced by 30% and grade drops one step.

**Earnings flag** (ENH-11): tickers with earnings within 2 days get a warning prepended to the analysis and are flagged in email/dashboard.

---

## Backtesting

The strategy has been backtested across **101 Nasdaq 100 tickers** (1-year daily bars, no-lookahead walk-forward).

**Key findings:**
- 35 of 101 tickers show positive expectancy with `--no-fib --stop 1.5% --tp 4.5%`
- Fibonacci levels help slow-moving stocks (ZS, CTSH, AMD) but hurt fast momentum names (NFLX, QCOM, INSM)
- The validated watchlist of 35 tickers is built into `universes.py`

```bash
# Run backtest on watchlist tickers
python -m backtest.engine --universe watchlist --no-fib --stop 1.5 --tp 4.5 -v --save-csv

# Auto-tune signal weights from backtest results
python -m backtest.weight_tuner output/backtest_*.csv --apply
```

---

## Validated paper trading universe

**35 tickers with demonstrated edge** (no-fib, stop=1.5%, tp=4.5%):

| Tier | Tickers | Criteria |
|------|---------|----------|
| **Tier 1** (9) | APP, NFLX, INSM, QCOM, AAPL, TTWO, MNST, SNDK, PANW | E ≥ 6, WR ≥ 43% |
| **Tier 2** (13) | KDP, ZS, INTU, AVGO, GOOGL, LRCX, NXPI, BKR, CMCSA, ADSK, CTSH, SNPS, CSCO | E = 2–6 |
| **Tier 3** (13) | ARM, ODFL, TSLA, PEP, MU, MDLZ, AMD, AMAT, COST, REGN, WDC, ORLY, VRSK | E > 0 |

**No-Fibonacci required** for: NFLX, QCOM, INSM, TTWO, MNST, PANW, INTU, LRCX, NXPI, BKR, CMCSA, KDP, TSLA, AVGO

---

## Setup

### Requirements

- Python **3.11** (not 3.12+, not 3.14 — pandas/yfinance ABI incompatibility)
- Node.js **22 LTS** (for web dashboard only)
- FMP API key (free tier works; Ultimate plan needed for real-time intraday bars)
- Alpaca account (free paper trading at alpaca.markets)

### 1. Python environment

```bash
git clone <your-repo>
cd intraday_scanner
python3.11 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configuration

```bash
cp .env.example .env
# Fill in your keys — minimum required: FMP_API_KEY
```

### 3. Node.js (dashboard only)

```bash
brew install node@22             # macOS
# or: download installer from nodejs.org

cd web/frontend
npm install
```

---

## Usage

### Terminal scanner

```bash
# Scan validated watchlist (recommended starting point)
python main.py --universe watchlist

# Scan Tier 1 only (9 highest-confidence tickers)
python main.py --universe watchlist_t1

# Scan full Nasdaq 100 (scanner finds signals, only trades watchlist)
python main.py --universe nasdaq100 --max 50

# Scan custom tickers
python main.py --tickers AAPL NVDA MSFT GOOGL

# Dry run — evaluate trades without submitting orders
python main.py --universe watchlist --dry-run

# Skip trading, just scan and email
python main.py --universe watchlist --no-trade
```

### Web dashboard

```bash
# Terminal 1 — FastAPI backend
source .venv/bin/activate
uvicorn web.api:app --reload --port 8000

# Terminal 2 — React dev server
cd web/frontend
npm run dev
# Open: http://localhost:5173
```

### Backtesting

```bash
# Backtest the validated config on watchlist
python -m backtest.engine --universe watchlist --no-fib --stop 1.5 --tp 4.5 -v

# Sweep parameters to find optimal settings
python -m backtest.engine --tickers AAPL NFLX QCOM --stop 1.5 --tp 4.5 --no-fib -v --save-csv
python -m backtest.engine --tickers AAPL NFLX QCOM --stop 2.0 --tp 6.0 --no-fib -v --save-csv

# Auto-tune weights from backtest CSV output
python -m backtest.weight_tuner output/backtest_*.csv
python -m backtest.weight_tuner output/backtest_*.csv --apply   # writes to conviction.py
```

---

## Paper trading

All paper trading uses **Alpaca** (free at alpaca.markets → Paper Trading). Get your paper API keys there.

**Important:** `ALPACA_PAPER=true` and `TRADE_ENABLED=false` are the defaults. You must explicitly set `TRADE_ENABLED=true` to execute any orders.

### How it works

When a scan completes, the trade engine evaluates each top pick against 7 gates:

1. Ticker on `WATCHLIST_EXCLUDE`? → block
2. `TRADE_WATCHLIST_ONLY=true` and ticker not on validated watchlist? → block
3. Score ≥ `TRADE_MIN_SCORE` (default 4)?
4. Conviction ≥ `TRADE_MIN_CONVICTION` (default 60%)?
5. Open positions < `TRADE_MAX_POSITIONS` (default 10)?
6. Already in position for this ticker?
7. Price valid?

Qualifying tickers are submitted as **bracket orders** (entry + stop loss + take profit in one Alpaca API call). Once submitted, **Alpaca manages the stop and take-profit automatically** — your program does not need to be running for exits to execute.

**Stop/TP levels are ticker-specific:**
- Tickers in `NO_FIB_TICKERS` → fixed % (stop=1.5%, tp=4.5%) — backtest-validated
- All other tickers → Fibonacci levels when available, otherwise fixed %
- ATR override: if ATR(14) × 1.5 gives a wider stop than Fibonacci/fixed, ATR wins

**Between scans**, `position_monitor.py` runs at the start of each hourly scan to check signal-flip exits and max-hold-period exits. These are secondary to Alpaca's bracket orders.

### Bracket order flow

```
Scanner runs at 9:35 AM
    ↓
AAPL signals: 8/10 BULL, conviction 84% (A+)
    ↓
trade_engine: all 7 gates pass
    ↓
Alpaca receives:
  BUY  13 shares AAPL @ $213.50 limit
    ├── Stop loss:   $210.29 (Fibonacci 61.8%)
    └── Take profit: $221.84 (Fibonacci 100% extension)
    ↓
Alpaca holds all 3 legs on their servers
Program can stop running — exits are automatic
    ↓
Next scan at 10:35 AM: position_monitor checks for signal flips
```

---

## Project structure

```
intraday_scanner/
├── config.py                    # All env vars — single source of truth
├── universes.py                 # 614 tickers across 5 universes +
│                                #   WATCHLIST (35 validated) + NO_FIB_TICKERS
├── scanner.py                   # Orchestrates full scan pipeline
├── main.py                      # CLI entry point (Click + Rich)
├── requirements.txt
│
├── data/
│   ├── fmp_client.py            # FMP /stable/ endpoints — quotes, extended-hours,
│   │                            #   constituents, company names, earnings calendar
│   ├── yahoo_client.py          # Async OHLCV fetch (40 concurrent workers)
│   └── company_names.py         # Static name lookup (517 entries)
│
├── signals/
│   ├── base.py                  # TickerAnalysis, SignalResult, Bias
│   ├── conviction.py            # Weighted scoring, grade, MTF penalty, earnings flag
│   ├── candle.py                # Signal 1 — candlestick patterns
│   ├── volume.py                # Signal 2 — volume vs 20-bar average
│   ├── sma.py                   # Signal 3 — SMA divergence
│   ├── gaps.py                  # Signal 4 — open gap detection
│   ├── stochastics.py           # Signal 5 — stochastic oscillator
│   ├── cci.py                   # Signal 6 — commodity channel index
│   ├── role_reversal.py         # Signal 7 — S/R role reversal
│   ├── relative_strength.py     # Signal 8 — outperformance vs SPY
│   ├── vwap.py                  # Signal 9 — VWAP with std deviation bands
│   ├── news_sentiment.py        # Signal 10 — FMP headline keyword scoring
│   ├── fibonacci.py             # Multi-day swing anchor + retracements + extensions
│   ├── atr.py                   # ATR(14) dynamic stop loss computation
│   └── multi_timeframe.py       # Hourly × daily signal alignment check
│
├── trading/
│   ├── alpaca_client.py         # Alpaca TradingClient wrapper (paper only by default)
│   ├── trade_engine.py          # Entry gates, position sizing, bracket order submission
│   ├── position_monitor.py      # Inter-scan stop/TP monitoring, P&L recording
│   └── pnl_tracker.py           # Trade ledger, win rate, R-multiple, expectancy
│
├── backtest/
│   ├── engine.py                # Walk-forward backtester (no lookahead, signal cache)
│   └── weight_tuner.py          # Auto-tune signal weights from backtest CSV output
│
├── utils/
│   ├── email_sender.py          # Rich HTML email with pick cards, trade section, P&L
│   ├── spreadsheet.py           # 4-sheet Excel workbook
│   ├── exporter.py              # CSV + JSON export
│   ├── holidays.py              # NYSE market holiday calendar (computed, no hardcoding)
│   └── logger.py                # Logging setup
│
├── web/
│   ├── api.py                   # FastAPI backend (9 endpoints)
│   └── frontend/
│       ├── src/App.jsx          # React dashboard (4 pages)
│       ├── src/index.css        # Terminal trading desk aesthetic
│       └── package.json         # Vite + React + Recharts
│
├── .env.example                 # All variables documented with defaults
├── .github/workflows/
│   └── trading_scanner.yml      # 7× daily GitHub Actions (9:35 AM–3:35 PM ET)
└── output/                      # Scan results, backtest CSVs, trade ledger (gitignored)
```

---

## Environment variables

### Required

| Variable | Description |
|----------|-------------|
| `FMP_API_KEY` | Financial Modeling Prep key. Free tier works; Ultimate plan for real-time intraday bars |

### Scan settings

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_UNIVERSE` | `major_us_markets` | Universe when `--universe` not specified |
| `MAX_TICKERS` | `500` | Cap per scan (0 = no limit) |
| `TOP_N_PICKS` | `5` | Top N bulls + bears in output |
| `FMP_BATCH_SIZE` | `5` | Tickers per FMP quote batch |
| `ASYNC_FETCH_WORKERS` | `40` | Concurrent threads for OHLCV fetch |
| `REQUEST_DELAY_MS` | `120` | Delay between sequential requests (fallback only) |
| `LOG_LEVEL` | `INFO` | DEBUG / INFO / WARNING / ERROR |

### Email

| Variable | Default | Description |
|----------|---------|-------------|
| `SMTP_HOST` | `smtp.gmail.com` | SMTP server |
| `SMTP_PORT` | `587` | 587 = STARTTLS, 465 = SSL |
| `SMTP_USER` | | Gmail address |
| `SMTP_PASSWORD` | | App Password (Gmail) |
| `EMAIL_FROM` | | Sender address |
| `EMAIL_TO` | | Comma-separated recipients |

### Alpaca paper trading

| Variable | Default | Description |
|----------|---------|-------------|
| `ALPACA_API_KEY` | | Paper trading API key from alpaca.markets |
| `ALPACA_SECRET_KEY` | | Paper trading secret key |
| `ALPACA_PAPER` | `true` | **Must stay true** unless explicitly testing live |
| `TRADE_ENABLED` | `false` | Master switch — must be `true` to execute any orders |
| `TRADE_WATCHLIST_ONLY` | `true` | Only trade backtest-validated tickers |
| `TRADE_MIN_CONVICTION` | `60.0` | Minimum conviction % to enter |
| `TRADE_MIN_SCORE` | `4` | Minimum net signal score (1–10) |
| `TRADE_MAX_POSITIONS` | `10` | Maximum simultaneous open positions |
| `TRADE_POSITION_SIZE_PCT` | `5.0` | Portfolio % per position |
| `TRADE_MAX_POSITION_USD` | `2000.0` | Hard dollar cap per position |
| `TRADE_STOP_LOSS_PCT` | `1.5` | Fixed % stop (used for NO_FIB tickers) |
| `TRADE_TAKE_PROFIT_PCT` | `4.5` | Fixed % TP (used for NO_FIB tickers) |
| `TRADE_ORDER_TYPE` | `limit` | `limit` or `market` |
| `TRADE_DIRECTION` | `both` | `both` / `long_only` / `short_only` |

---

## Disclaimer

For educational and research purposes only. Not financial advice. Paper trading only by default. Past backtest performance does not guarantee future results. Always apply your own risk management.
