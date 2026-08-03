import { NextRequest, NextResponse } from "next/server";
import type { AnalyzeResult } from "@/lib/types";

// The Python engine runs the live scan. Point this at either a local
// `uvicorn web.api:app` server or the AWS Lambda Function URL. Defaults to the
// local dev server. Trailing slash stripped so Function URLs work as-is.
const API_BASE = (process.env.SCANNER_API_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  ""
);

// Shared secret for the public Lambda Function URL. Sent server-side only, so
// it never reaches the browser. Must match ANALYZE_API_TOKEN on the Lambda.
const API_TOKEN = (process.env.ANALYZE_API_TOKEN ?? "").trim();

// Always run live — never cache on-demand analyses.
export const dynamic = "force-dynamic";
export const revalidate = 0;

const MAX_TICKERS = 10;

export async function GET(req: NextRequest) {
  const raw = req.nextUrl.searchParams.get("tickers") ?? "";

  const tickers = Array.from(
    new Set(
      raw
        .split(/[\s,]+/)
        .map((t) => t.trim().toUpperCase())
        .filter(Boolean)
    )
  ).slice(0, MAX_TICKERS);

  if (tickers.length === 0) {
    return NextResponse.json(
      { error: "Enter at least one ticker (e.g. AAPL, NVDA)." },
      { status: 400 }
    );
  }

  const results: AnalyzeResult[] = await Promise.all(
    tickers.map(async (ticker): Promise<AnalyzeResult> => {
      try {
        const url = `${API_BASE}/api/signals/${encodeURIComponent(
          ticker
        )}?hourly=true`;
        const r = await fetch(url, {
          cache: "no-store",
          headers: API_TOKEN ? { "x-api-token": API_TOKEN } : undefined,
        });

        if (!r.ok) {
          let detail = "";
          try {
            const body = await r.json();
            detail = body?.detail ?? "";
          } catch {
            detail = await r.text().catch(() => "");
          }
          return {
            ticker,
            error:
              r.status === 404
                ? detail || `No data for ${ticker}.`
                : `Engine error (HTTP ${r.status})${
                    detail ? `: ${String(detail).slice(0, 160)}` : ""
                  }`,
          };
        }

        const data = await r.json();
        return { ticker, data };
      } catch (e) {
        return {
          ticker,
          error:
            `Could not reach the scanner engine at ${API_BASE}. ` +
            `Start it with: uvicorn web.api:app --port 8000` +
            (e instanceof Error ? ` (${e.message})` : ""),
        };
      }
    })
  );

  return NextResponse.json({ results, api: API_BASE });
}
