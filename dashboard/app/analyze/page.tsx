"use client";

import { useState } from "react";
import type {
  AnalyzeResponse,
  AnalyzeResult,
  AnalyzePayload,
  AnalyzeFib,
} from "@/lib/types";

function fmt(n: number | null | undefined, dp = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-US", {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  });
}

function biasClass(bias: string): string {
  const b = bias.toLowerCase();
  if (b === "bull" || b === "bullish") return "bull";
  if (b === "bear" || b === "bearish") return "bear";
  return "neutral";
}

function biasArrow(bias: string): string {
  const c = biasClass(bias);
  return c === "bull" ? "▲" : c === "bear" ? "▼" : "—";
}

function dirClass(dir: string): string {
  const d = dir.toUpperCase();
  if (d.includes("LONG") || d.includes("BULL")) return "bull";
  if (d.includes("SHORT") || d.includes("BEAR")) return "bear";
  return "neutral";
}

function TargetBlock({ fib, price }: { fib: AnalyzeFib | null; price: number }) {
  if (!fib || fib.next_target === null || fib.next_target === undefined) {
    return (
      <div className="target-block">
        <div className="target-label">~1-Hour Fib Target</div>
        <div className="target-value neutral">No clean setup</div>
        <div className="target-sub">
          No high-conviction Fibonacci target on the current hourly structure.
        </div>
      </div>
    );
  }
  const up = fib.next_target >= price;
  const move = price ? ((fib.next_target / price - 1) * 100) : 0;
  return (
    <div className="target-block">
      <div className="target-label">~1-Hour Fib Target</div>
      <div className={`target-value ${up ? "bull" : "bear"}`}>
        ${fmt(fib.next_target)}
      </div>
      <div className="target-sub">
        {fib.next_label || "target"} · {up ? "+" : ""}
        {fmt(move)}% from ${fmt(price)}
      </div>
      <div className="target-grid">
        <div>
          <span className="tg-k">Entry</span>
          <span className="tg-v">${fmt(fib.entry_price)}</span>
        </div>
        <div>
          <span className="tg-k">Stop</span>
          <span className="tg-v">${fmt(fib.stop_loss)}</span>
        </div>
        <div>
          <span className="tg-k">R:R</span>
          <span className="tg-v">
            {fib.risk_reward_t1 ? `${fmt(fib.risk_reward_t1, 1)}×` : "—"}
          </span>
        </div>
      </div>
    </div>
  );
}

function ResultCard({ data }: { data: AnalyzePayload }) {
  const cs = data.conviction;
  const dcls = dirClass(cs?.direction ?? "NEUTRAL");
  const chgUp = (data.chg_pct ?? 0) >= 0;
  return (
    <div className="analyze-card">
      <div className="ac-head">
        <div>
          <div className="ac-ticker">{data.ticker}</div>
          <div className="ac-price">
            ${fmt(data.price)}{" "}
            <span className={chgUp ? "bull" : "bear"}>
              {chgUp ? "+" : ""}
              {fmt(data.chg_pct)}%
            </span>
          </div>
        </div>
        <div className="ac-verdict">
          <span className={`dir-badge ${dcls}`}>
            {cs?.direction ?? "NEUTRAL"}
          </span>
          <div className="ac-grade">
            Grade {cs?.grade ?? "—"} · {data.mode}
          </div>
        </div>
      </div>

      <div className="ac-conviction">
        <div className="conv-top">
          <span className="conv-label">Conviction</span>
          <span className={`conv-pct ${dcls}`}>
            {fmt(cs?.conviction_pct, 0)}%
          </span>
        </div>
        <div className="conv-bar-bg">
          <div
            className={`conv-bar-fill ${dcls}`}
            style={{ width: `${Math.min(100, Math.max(0, cs?.conviction_pct ?? 0))}%` }}
          />
        </div>
        <div className="conv-score">
          net {data.net_score >= 0 ? "+" : ""}
          {data.net_score} · weighted {fmt(cs?.weighted_score, 1)}
        </div>
      </div>

      <TargetBlock fib={data.fib} price={data.price} />

      <div className="sig-section-title">10 Signals</div>
      <div className="sig-list">
        {data.signals.map((s) => {
          const c = biasClass(s.bias);
          return (
            <div className="sig-row" key={s.name}>
              <span className="sig-name">{s.name}</span>
              <span className={`sig-val ${c}`} title={s.detail}>
                {biasArrow(s.bias)} {s.label}
              </span>
            </div>
          );
        })}
      </div>

      {cs?.analysis && <div className="ac-analysis">{cs.analysis}</div>}
      {cs?.key_signals && cs.key_signals.length > 0 && (
        <div className="ac-keysig">
          {cs.key_signals.map((k, i) => (
            <span className="keysig-chip" key={i}>
              {k}
            </span>
          ))}
        </div>
      )}
      <div className="ac-asof">as of {new Date(data.as_of).toLocaleString()}</div>
    </div>
  );
}

export default function AnalyzePage() {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<AnalyzeResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function runAnalyze(e?: React.FormEvent) {
    e?.preventDefault();
    const q = input.trim();
    if (!q || loading) return;
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`/api/analyze?tickers=${encodeURIComponent(q)}`, {
        cache: "no-store",
      });
      const body = (await r.json()) as AnalyzeResponse & { error?: string };
      if (!r.ok) {
        setError(body?.error ?? `Request failed (HTTP ${r.status})`);
        setResults(null);
      } else {
        setResults(body.results);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setResults(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <div className="topbar">
        <div>
          <div className="page-title">Analyze Ticker</div>
          <div className="page-sub">
            Enter any ticker(s) to run the live engine — 10 signals, conviction,
            and a Fibonacci target for roughly the next hour.
          </div>
        </div>
      </div>

      <form className="analyze-form" onSubmit={runAnalyze}>
        <input
          className="analyze-input"
          placeholder="e.g. AAPL, NVDA, TSLA"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          autoFocus
        />
        <button className="analyze-btn" type="submit" disabled={loading || !input.trim()}>
          {loading ? "Running…" : "Analyze"}
        </button>
      </form>

      {error && <div className="analyze-error">{error}</div>}

      {!results && !error && !loading && (
        <div className="empty-hint">
          Type one or more tickers (comma or space separated) and press Enter.
          Targets are computed on hourly bars, so re-run through the session for a
          fresh next-hour projection.
        </div>
      )}

      {results && (
        <div className="analyze-grid">
          {results.map((res) =>
            res.data ? (
              <ResultCard key={res.ticker} data={res.data} />
            ) : (
              <div className="analyze-card error-card" key={res.ticker}>
                <div className="ac-ticker">{res.ticker}</div>
                <div className="analyze-error" style={{ marginTop: 8 }}>
                  {res.error}
                </div>
              </div>
            )
          )}
        </div>
      )}
    </>
  );
}
