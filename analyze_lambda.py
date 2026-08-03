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

The dashboard then calls:  {SCANNER_API_URL}/api/signals/{TICKER}?hourly=true
"""
from __future__ import annotations

import json
import logging

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

    hourly = str(qs.get("hourly", "false")).lower() in ("1", "true", "yes")

    from utils.analyze import analyze_ticker, InsufficientData

    try:
        return _resp(200, analyze_ticker(ticker, hourly=hourly))
    except InsufficientData as e:
        return _resp(404, {"detail": str(e)})
    except Exception as e:  # noqa: BLE001
        log.exception("analyze_ticker failed for %s", ticker)
        return _resp(500, {"detail": str(e)})
