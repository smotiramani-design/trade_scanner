import Link from "next/link";

/**
 * Compact Fib vs ATR reminder on Today + Daily pages.
 * Full write-up lives at /guide.
 */
export default function StrategyKey() {
  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <div className="panel-title">Trade plan key · Fib vs ATR</div>
      <ol className="ml-steps">
        <li>
          <strong>Fib row</strong> — structure plan (entry / stop / T1 / T2).
          Ranking and hit stats use this.
        </li>
        <li>
          <strong>ATR row</strong> — volatility plan: stop = 1.5× ATR, T1 = 1R,
          T2 = 2R. Does not replace Fib.
        </li>
        <li>
          <strong>Together</strong> — wider stop wins; scale at the nearer T1;
          runner toward the farther T2.
        </li>
      </ol>
      <p className="ml-note" style={{ marginTop: 8 }}>
        Full field-by-field guide (Fib, ATR, ML filters):{" "}
        <Link href="/guide">Open Guide →</Link>
      </p>
    </div>
  );
}
