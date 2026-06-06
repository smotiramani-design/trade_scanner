# Trading Signal Scanner

Intraday technical scanner for US equities. Analyzes any ticker, index universe (S&P 500, Nasdaq 100, Dow Jones), or custom list using **7 signals**:

| # | Signal | Description |
|---|--------|-------------|
| 1 | **Candle pattern** | Engulfing, harami, hammer, shooting star, stale runs |
| 2 | **Volume** | Current bar vs 20-bar average trend |
| 3 | **SMA divergence** | % distance from 20-period SMA |
| 4 | **Gaps** | Open unfilled gaps above/below price |
| 5 | **Stochastics** | %K / %D overbought/oversold + crossover |
| 6 | **CCI** | Commodity Channel Index ±100 levels + zero-line cross |
| 7 | **Role reversal** | Prior support/resistance flip + SMA as S/R |

**Data sources**
- Real-time quotes → [Financial Modeling Prep](https://financialmodelingprep.com) (FMP)
- OHLCV history → Yahoo Finance via `yfinance`
  - Market open  → 1-hour bars, 3-month window
  - Market closed → daily bars, 1-year window

---

## Setup

### 1. Clone / download the project

```bash
git clone <your-repo>
cd trading_scanner
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure API keys

```bash
cp .env.example .env
```

Open `.env` and fill in your FMP API key:

```
FMP_API_KEY=your_actual_key_here
```

Get a free key at https://financialmodelingprep.com/developer/docs/

> **Never commit `.env`** — it's listed in `.gitignore`.

---

## Usage

```bash
# Scan top 20 S&P 500 tickers (auto market-hours detection)
python main.py --universe sp500 --max 20

# Scan Nasdaq 100, top 50 tickers
python main.py --universe nasdaq100 --max 50

# Force daily chart mode (regardless of market hours)
python main.py --universe sp500 --max 30 --daily

# Scan custom tickers
python main.py --tickers AAPL,MSFT,NVDA,TSLA,AMD

# Show only strong bullish signals
python main.py --universe sp500 --max 100 --filter strong_bull

# Show top 10 results only
python main.py --universe nasdaq100 --max 50 --top 10

# Full signal breakdown for a specific ticker
python main.py --universe sp500 --max 50 --detail AAPL

# Save results to CSV
python main.py --universe sp500 --max 50 --save
```

### Filter options

| Flag | Meaning |
|------|---------|
| `all` | All tickers (default) |
| `bull` | Net score ≥ +1 |
| `bear` | Net score ≤ −1 |
| `strong_bull` | Net score ≥ +4 |
| `strong_bear` | Net score ≤ −4 |

### Signal key in output

```
▲  =  Bullish signal
▼  =  Bearish signal
—  =  Neutral
```

Net score ranges from −7 (all bearish) to +7 (all bullish).

---

## Project structure

```
trading_scanner/
├── .env.example          # copy to .env and fill in keys
├── .gitignore            # excludes .env, output/, __pycache__, etc.
├── config.py             # loads .env, exposes typed settings
├── universes.py          # S&P 500, Nasdaq 100, Dow Jones ticker lists
├── scanner.py            # orchestrates the full scan pipeline
├── main.py               # CLI entry point (Click + Rich)
├── requirements.txt
├── data/
│   ├── fmp_client.py     # FMP real-time quote API
│   └── yahoo_client.py   # Yahoo Finance OHLCV history
├── signals/
│   ├── base.py           # Bias enum, SignalResult, TickerAnalysis
│   ├── candle.py         # Signal 1: candlestick patterns
│   ├── volume.py         # Signal 2: volume vs trend
│   ├── sma.py            # Signal 3: SMA divergence
│   ├── gaps.py           # Signal 4: open gap detection
│   ├── stochastics.py    # Signal 5: stochastic oscillator
│   ├── cci.py            # Signal 6: commodity channel index
│   └── role_reversal.py  # Signal 7: support/resistance flip
├── utils/
│   ├── logger.py         # logging config
│   └── exporter.py       # CSV / JSON output
└── output/               # scan results saved here (gitignored)
```

---

## Environment variables reference

| Variable | Default | Description |
|----------|---------|-------------|
| `FMP_API_KEY` | *(required)* | FMP API key |
| `LOG_LEVEL` | `INFO` | DEBUG / INFO / WARNING / ERROR |
| `OUTPUT_DIR` | `output` | where CSV/JSON files are saved |
| `SAVE_CSV` | `true` | auto-save CSV on `--save` |
| `SAVE_JSON` | `false` | also save JSON |
| `DEFAULT_UNIVERSE` | `sp500` | default universe if none specified |
| `MAX_TICKERS` | `50` | default cap per scan |
| `FMP_BATCH_SIZE` | `5` | tickers per FMP quote request |
| `REQUEST_DELAY_MS` | `150` | ms between Yahoo history requests |

---

## Disclaimer

For educational purposes only. Not financial advice. Always apply your own risk management before trading.
