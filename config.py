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

# ── SMS (Twilio) ──────────────────────────────────────────────────────────────
TWILIO_ACCOUNT_SID:  str  = _get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN:   str  = _get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER:  str  = _get("TWILIO_FROM_NUMBER", "")
SMS_TO_NUMBERS:      list = _list("SMS_TO_NUMBERS")
SMS_ENABLED: bool = bool(
    TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER and SMS_TO_NUMBERS
)

# ── Output / Logging ──────────────────────────────────────────────────────────
LOG_LEVEL: str    = _get("LOG_LEVEL", "INFO").upper()
OUTPUT_DIR: Path  = _ROOT / _get("OUTPUT_DIR", "output")
SAVE_CSV: bool    = _bool("SAVE_CSV", True)
SAVE_JSON: bool   = _bool("SAVE_JSON", False)

# ── Scan defaults ─────────────────────────────────────────────────────────────
DEFAULT_UNIVERSE: str = _get("DEFAULT_UNIVERSE", "sp500")
MAX_TICKERS: int      = _int("MAX_TICKERS", 500)
FMP_BATCH_SIZE: int   = _int("FMP_BATCH_SIZE", 5)
REQUEST_DELAY_MS: int = _int("REQUEST_DELAY_MS", 120)
TOP_N_PICKS: int      = _int("TOP_N_PICKS", 5)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
