"""
analyze_lambda.py — AWS Lambda Function URL handler for on-demand ticker analysis.

This is the production compute endpoint behind the dashboard's "Analyze Ticker"
page. It mirrors web/api.py's GET /api/signals/{ticker} so the dashboard's
server-side proxy (/api/analyze) works against EITHER a local uvicorn server or
this Lambda — just point SCANNER_API_URL at the right base URL.

Deploy
------
1. Reuse the same zip as the other Lambdas (build_lambda_zip.sh already bundles
   this file + utils/analyze.py + the engine).
2. Create a new Lambda function (or reuse one) with handler:
       analyze_lambda.handler
   Give it enough memory/timeout (e.g. 512 MB, 30 s) — it pulls live bars.
3. Configuration → Function URL → Create:
       Auth type: NONE
       (optionally restrict CORS to your Vercel domain)
4. In Vercel, set the dashboard env var:
       SCANNER_API_URL = https://<id>.lambda-url.<region>.on.aws
   (no trailing slash needed; the proxy strips it)

Locking it down (recommended, since Auth type is NONE)
------------------------------------------------------
Set a shared secret so only your dashboard can call it:
  • On this Lambda:  ANALYZE_API_TOKEN = <some-long-random-string>
  • In Vercel:       ANALYZE_API_TOKEN = <same-string>
The dashboard proxy sends it as the `x-api-token` header; requests without it
get 401. If ANALYZE_API_TOKEN is unset, the endpoint stays open.

The dashboard then calls:  {SCANNER_API_URL}/api/signals/{TICKER}?hourly=true
"""
from __future__ import annotations

import hmac
import json
import logging
import os

log = logging.getLogger()
if not log.handlers:
    logging.basicConfig(level=logging.INFO)

_CORS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
    "Access-Control-Allow-Headers": "*",
}


def _resp(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", **_CORS},
        "body": json.dumps(body),
    }


def _extract(event: dict):
    """Pull (method, path, query) from a Function URL (payload v2) or API GW event."""
    rc = event.get("requestContext", {}) or {}
    method = (rc.get("http", {}) or {}).get("method") or event.get("httpMethod") or "GET"
    path = event.get("rawPath") or event.get("path") or "/"
    qs = event.get("queryStringParameters") or {}
    return method, path, qs


def _authorized(event: dict, qs: dict) -> bool:
    """
    Shared-secret gate. If ANALYZE_API_TOKEN is set on the function, callers must
    present the same value via the `x-api-token` header (preferred) or `?token=`.
    If the env var is unset, the endpoint stays open (dev / local FastAPI parity).
    """
    expected = (os.environ.get("ANALYZE_API_TOKEN") or "").strip()
    if not expected:
        return True

    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    provided = (headers.get("x-api-token") or qs.get("token") or "").strip()
    return bool(provided) and hmac.compare_digest(provided, expected)


def handler(event=None, context=None) -> dict:
    event = event or {}
    method, path, qs = _extract(event)

    if method == "OPTIONS":
        return _resp(200, {"ok": True})

    if path.rstrip("/") in ("", "/api/health"):
        return _resp(200, {"status": "ok"})

    # Path form: /api/signals/{ticker}  (fallback to ?ticker= / ?tickers=)
    ticker = None
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 3 and parts[0] == "api" and parts[1] == "signals":
        ticker = parts[2]
    ticker = ticker or qs.get("ticker") or qs.get("tickers")

    if not ticker:
        return _resp(400, {"detail": "Provide a ticker: /api/signals/{TICKER}?hourly=true"})

    if not _authorized(event, qs):
        return _resp(401, {"detail": "Unauthorized"})

    hourly = str(qs.get("hourly", "false")).lower() in ("1", "true", "yes")

    from utils.analyze import analyze_ticker, InsufficientData

    try:
        return _resp(200, analyze_ticker(ticker, hourly=hourly))
    except InsufficientData as e:
        return _resp(404, {"detail": str(e)})
    except Exception as e:  # noqa: BLE001
        log.exception("analyze_ticker failed for %s", ticker)
        return _resp(500, {"detail": str(e)})
