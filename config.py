"""
config.py — single source of truth for all settings.
Loads .env at import time; every other module imports from here.
Nothing in the codebase calls os.environ directly.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

_ROOT = Path(__file__).parent
load_dotenv(_ROOT / ".env", override=False)


def _require(key: str) -> str:
    val = os.getenv(key, "").strip()
    if not val:
        raise EnvironmentError(
            f"Required env variable '{key}' is missing.\n"
            f"Copy .env.example → .env and fill in your values."
        )
    return val


def _get(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in ("1", "true", "yes")


def _int(key: str, default: int = 0) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _list(key: str, default: str = "") -> list:
    raw = os.getenv(key, default).strip()
    return [v.strip() for v in raw.split(",") if v.strip()] if raw else []


# ── FMP ──────────────────────────────────────────────────────────────────────
FMP_API_KEY: str = _require("FMP_API_KEY")

# ── Email ────────────────────────────────────────────────────────────────────
SMTP_HOST: str       = _get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int       = _int("SMTP_PORT", 587)
SMTP_USER: str       = _get("SMTP_USER", "")
SMTP_PASSWORD: str   = _get("SMTP_PASSWORD", "")
EMAIL_FROM: str      = _get("EMAIL_FROM", "")
EMAIL_FROM_NAME: str = _get("EMAIL_FROM_NAME", "Trading Scanner")
EMAIL_TO: list       = _list("EMAIL_TO")
EMAIL_SUBJECT: str   = _get("EMAIL_SUBJECT", "Trading Signal Scanner — Top 5 Picks")
EMAIL_ENABLED: bool  = bool(SMTP_USER and SMTP_PASSWORD and EMAIL_TO)

# SMS removed — use email notifications

# ── Output / Logging ──────────────────────────────────────────────────────────
LOG_LEVEL: str    = _get("LOG_LEVEL", "INFO").upper()
OUTPUT_DIR: Path  = _ROOT / _get("OUTPUT_DIR", "output")
SAVE_CSV: bool    = _bool("SAVE_CSV", True)
SAVE_JSON: bool   = _bool("SAVE_JSON", False)

# ── Personal watchlist (ENH-15) ───────────────────────────────────────────────
# Comma-separated tickers always included in every scan, regardless of universe.
# Example: PERSONAL_WATCHLIST=AAPL,TSLA,NVDA,MSFT
# These are merged into ticker_list at the start of main.py.
_pw_raw = _get("PERSONAL_WATCHLIST", "")
PERSONAL_WATCHLIST: list = [t.strip().upper() for t in _pw_raw.split(",") if t.strip()] if _pw_raw else []

# ── Scan defaults ─────────────────────────────────────────────────────────────
DEFAULT_UNIVERSE: str = _get("DEFAULT_UNIVERSE", "major_us_markets")
MAX_TICKERS: int      = _int("MAX_TICKERS", 500)
FMP_BATCH_SIZE: int   = _int("FMP_BATCH_SIZE", 5)
REQUEST_DELAY_MS:    int  = _int("REQUEST_DELAY_MS", 120)
ASYNC_FETCH_WORKERS: int  = _int("ASYNC_FETCH_WORKERS", 40)   # concurrent threads for bar fetch (ENH-06)
TOP_N_PICKS: int      = _int("TOP_N_PICKS", 5)

try:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    # Read-only filesystem (e.g. AWS Lambda, where only /tmp is writable).
    OUTPUT_DIR = Path("/tmp/output")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Alpaca Paper Trading ──────────────────────────────────────────────────────
ALPACA_API_KEY:    str  = _get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY: str  = _get("ALPACA_SECRET_KEY", "")
ALPACA_PAPER:      bool = _bool("ALPACA_PAPER", True)   # default True = paper only
ALPACA_ENABLED:    bool = bool(ALPACA_API_KEY and ALPACA_SECRET_KEY)

# ── Trade execution settings ──────────────────────────────────────────────────
TRADE_ENABLED:           bool  = _bool("TRADE_ENABLED", False)   # master switch
TRADE_MIN_CONVICTION:    float = float(_get("TRADE_MIN_CONVICTION", "70.0"))
TRADE_MIN_SCORE:         int   = _int("TRADE_MIN_SCORE", 4)
TRADE_MAX_POSITIONS:     int   = _int("TRADE_MAX_POSITIONS", 10)
TRADE_POSITION_SIZE_PCT: float = float(_get("TRADE_POSITION_SIZE_PCT", "5.0"))
TRADE_MAX_POSITION_USD:  float = float(_get("TRADE_MAX_POSITION_USD", "2000.0"))
TRADE_STOP_LOSS_PCT:     float = float(_get("TRADE_STOP_LOSS_PCT", "2.0"))
TRADE_TAKE_PROFIT_PCT:   float = float(_get("TRADE_TAKE_PROFIT_PCT", "4.0"))
TRADE_ORDER_TYPE:        str   = _get("TRADE_ORDER_TYPE", "limit").lower()
TRADE_LIMIT_OFFSET_PCT:  float = float(_get("TRADE_LIMIT_OFFSET_PCT", "0.05"))
TRADE_DIRECTION:         str   = _get("TRADE_DIRECTION", "both").lower()
TRADE_WATCHLIST_ONLY:    bool  = _bool("TRADE_WATCHLIST_ONLY", True)   # True = only trade backtest-validated tickers
GREEKS_ENABLED:          bool  = _bool("GREEKS_ENABLED", False)         # ENH-20: fetch option chain for gamma sizing   # True = only trade backtest-validated tickers

# ── Database (Supabase / Postgres) ────────────────────────────────────────────
# Scan results + trades are written here instead of (or alongside) email.
# DATABASE_URL is the Postgres connection string from Supabase
#   (Project → Settings → Database → Connection string → URI).
# Example: postgresql://postgres:[PASSWORD]@db.<ref>.supabase.co:5432/postgres
DATABASE_URL: str  = _get("DATABASE_URL", "")
DB_ENABLED:   bool = _bool("DB_ENABLED", bool(DATABASE_URL))   # auto-on when a URL is set
