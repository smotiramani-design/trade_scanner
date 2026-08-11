import Link from "next/link";

export const revalidate = 3600;

export default function GuidePage() {
  return (
    <>
      <div className="topbar">
        <div>
          <div className="page-title">Guide</div>
          <div className="page-sub">
            How to read pick cards — Fib, ATR R-multiples, and ML filters
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-title">What you see on a card</div>
        <p className="ml-note" style={{ marginTop: 0 }}>
          Each pick can show up to three level rows. Fib and ATR are{" "}
          <em>trade plans</em>. The ML row is a <em>filter / size hint</em> —
          it does not set entry, stop, or targets by itself.
        </p>
        <table className="data-table" style={{ marginTop: 12 }}>
          <thead>
            <tr>
              <th>Row</th>
              <th>Purpose</th>
              <th>Drives ranking?</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="mono">Fib …</td>
              <td>Structure plan from the swing range</td>
              <td>Yes (hit stats + P(hit) label)</td>
            </tr>
            <tr>
              <td className="mono">ATR …</td>
              <td>Volatility plan in R-multiples</td>
              <td>No — parallel only</td>
            </tr>
            <tr>
              <td className="mono">Pred / Ens / EV</td>
              <td>Model filters and expected-move hint</td>
              <td>No — parallel only</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-title">Fibonacci plan</div>
        <ol className="ml-steps">
          <li>
            <strong>Fib entry</strong> — ideal pullback/bounce (~38.2%
            retracement of the swing).
          </li>
          <li>
            <strong>Fib stop</strong> — invalidation (~61.8% retracement). If
            price gets here, the Fib thesis is wrong.
          </li>
          <li>
            <strong>Fib T1 / T2</strong> — extension targets (measured move /
            stretch). The primary Fib take-profit is what “1hr hit” / “Day hit”
            validates.
          </li>
          <li>
            Direction always matches weighted conviction (bull picks = upside
            targets, bear picks = downside).
          </li>
        </ol>
        <p className="ml-note">
          Use Fib when you want levels tied to the day’s structure. Hit-rate
          charts on Today / Daily still measure this plan only.
        </p>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-title">ATR R-multiple plan</div>
        <ol className="ml-steps">
          <li>
            <strong>ATR entry</strong> — scan price (market-style at signal
            time).
          </li>
          <li>
            <strong>ATR stop</strong> — 1.5× ATR(14) away from entry. Adapts to
            how wild the name usually moves.
          </li>
          <li>
            <strong>R</strong> = |entry − stop|. One unit of risk.
          </li>
          <li>
            <strong>ATR T1 · 1R</strong> — first target at +1R (1:1).{" "}
            <strong>ATR T2 · 2R</strong> — second target at +2R (1:2).
          </li>
        </ol>
        <p className="ml-note">
          ATR does <em>not</em> replace Fib. It answers: “Given this stock’s
          volatility, where is a clean 1R / 2R payoff from here?”
        </p>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-title">How to use Fib + ATR together</div>
        <ol className="ml-steps">
          <li>
            Only act when both plans agree on <strong>direction</strong> (they
            should — same conviction).
          </li>
          <li>
            Prefer the <strong>wider stop</strong> (more room / fewer noise
            stops). Example: Fib stop $98, ATR stop $96.50 → use $96.50.
          </li>
          <li>
            Scale out at the <strong>nearer T1</strong>; leave a runner toward
            the farther T2. Example: ATR T1 $101, Fib T1 $103 → bank near $101,
            trail for Fib T1/T2.
          </li>
          <li>
            If ATR T1 is far beyond Fib T2 (or vice versa), treat the closer
            level as realistic and the farther as stretch.
          </li>
        </ol>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-title">ML fields (when present)</div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Field</th>
              <th>Meaning</th>
              <th>How to use</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="mono">P(hit)</td>
              <td>Logistic probability Fib target hits</td>
              <td>Already ranks the pick list</td>
            </tr>
            <tr>
              <td className="mono">Ens P(hit)</td>
              <td>Average of logistic + LightGBM + XGBoost</td>
              <td>Second opinion — prefer ≥ ~55–60%</td>
            </tr>
            <tr>
              <td className="mono">Pred mid</td>
              <td>Typical favourable move (model)</td>
              <td>If below Fib T1, take T1 as stretch</td>
            </tr>
            <tr>
              <td className="mono">Risk mid</td>
              <td>Typical adverse (stop-side) move</td>
              <td>Cut size if risk looks large vs Pred</td>
            </tr>
            <tr>
              <td className="mono">EV</td>
              <td>Rough hit×upside − miss×downside</td>
              <td>Prefer green EV; treat red as caution</td>
            </tr>
          </tbody>
        </table>
        <p className="ml-note" style={{ marginTop: 12 }}>
          Deeper model pages:{" "}
          <Link href="/ml/ensemble">Ensemble</Link> ·{" "}
          <Link href="/ml/ranges">Ranges</Link> ·{" "}
          <Link href="/ml/risk">Risk</Link> ·{" "}
          <Link href="/ml">Weights</Link>
        </p>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-title">Simple daily checklist</div>
        <ol className="ml-steps">
          <li>
            Open <Link href="/">Today</Link> (intraday) or{" "}
            <Link href="/momentum">Daily Scans</Link> — start from top-ranked
            picks.
          </li>
          <li>Read Fib row = structure thesis; ATR row = volatility payoff.</li>
          <li>Pick stop = wider of Fib vs ATR; first target = nearer T1.</li>
          <li>
            Optional filter: Ens P(hit) strong + EV green before sizing up.
          </li>
          <li>
            Need a one-off ticker? Use{" "}
            <Link href="/analyze">Analyze Ticker</Link> — shows Fib + ATR for
            any symbol.
          </li>
        </ol>
      </div>
    </>
  );
}
