import {
  getLatestBoostedRun,
  getBoostedRuns,
  getRecentRiskPicks,
} from "@/lib/boosted-queries";
import type { BoostedRunRow, PickRow } from "@/lib/types";

export const revalidate = 60;

function fmt(n: number | null | undefined, digits = 1, suffix = ""): string {
  if (n == null) return "—";
  return `${n.toFixed(digits)}${suffix}`;
}

function fmtPrice(n: number | null | undefined) {
  if (n == null) return "—";
  return `$${n.toFixed(2)}`;
}

export default async function RiskRangesPage() {
  let latest: BoostedRunRow | null = null;
  let runs: BoostedRunRow[] = [];
  let picks: PickRow[] = [];
  let err: string | null = null;
  try {
    [latest, runs, picks] = await Promise.all([
      getLatestBoostedRun(),
      getBoostedRuns(20),
      getRecentRiskPicks(30),
    ]);
  } catch (e) {
    err = e instanceof Error ? e.message : String(e);
  }

  if (err) {
    return (
      <>
        <div className="topbar">
          <div>
            <div className="page-title">Risk Ranges</div>
            <div className="page-sub">Connection error</div>
          </div>
        </div>
        <div className="error-box">
          Could not load risk model data: <code>{err}</code>
        </div>
      </>
    );
  }

  if (!latest || latest.adv_n_samples == null) {
    return (
      <>
        <div className="topbar">
          <div>
            <div className="page-title">Risk Ranges</div>
            <div className="page-sub">
              LightGBM quantile model of adverse (stop-side) Fib-window move
            </div>
          </div>
        </div>
        <div className="empty-state">
          <div className="icon">🛡</div>
          <p>No adverse/risk model logged yet.</p>
          <p className="hint">
            Run <code>python -m backtest.boosted_tuner --save-db</code>. Needs
            labeled rows with window highs/lows from the 4 PM validator.
          </p>
        </div>
      </>
    );
  }

  const coverage = latest.adv_test_coverage ?? {};
  const mae = latest.adv_test_mae ?? {};
  const importance = latest.adv_importance ?? [];

  return (
    <>
      <div className="topbar">
        <div>
          <div className="page-title">Risk Ranges</div>
          <div className="page-sub">
            Adverse excursion quantiles · run #{latest.id} ·{" "}
            {latest.trade_date} {latest.et_time} ET
          </div>
        </div>
        <span className="ml-flag">stop-side band · does not change Fib stops</span>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-label">Samples</div>
          <div className="stat-value">{latest.adv_n_samples ?? "—"}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Mean adverse</div>
          <div className="stat-value">{fmt(latest.adv_mean_excursion, 2, "%")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Median adverse</div>
          <div className="stat-value">{fmt(latest.adv_median_excursion, 2, "%")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Q50 coverage</div>
          <div className="stat-value">{fmt(coverage["0.50"], 2)}</div>
        </div>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-title">Walk-forward MAE / coverage</div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Quantile</th>
              <th>MAE</th>
              <th>Coverage</th>
            </tr>
          </thead>
          <tbody>
            {["0.25", "0.50", "0.75"].map((q) => (
              <tr key={q}>
                <td className="mono">{q}</td>
                <td className="mono">{fmt(mae[q], 4)}</td>
                <td className="mono">{fmt(coverage[q], 3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {importance.length > 0 && (
        <div className="panel" style={{ marginTop: 16 }}>
          <div className="panel-title">Feature importance (median model)</div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Feature</th>
                <th>Gain</th>
              </tr>
            </thead>
            <tbody>
              {importance.slice(0, 10).map((item) => (
                <tr key={item.name}>
                  <td className="mono">{item.name}</td>
                  <td className="mono">{item.gain.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-title">Recent picks with risk bands</div>
        {picks.length === 0 ? (
          <p className="hint" style={{ padding: 12 }}>
            No picks with <code>adv_mid</code> yet — next scan after training
            will populate them.
          </p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Ticker</th>
                <th>Dir</th>
                <th>Price</th>
                <th>Adv lo</th>
                <th>Adv mid</th>
                <th>Adv hi</th>
                <th>EV</th>
              </tr>
            </thead>
            <tbody>
              {picks.map((p) => (
                <tr key={`${p.scan_id}-${p.ticker}-${p.direction}`}>
                  <td className="mono">
                    {p.trade_date} {p.et_time}
                  </td>
                  <td className="mono">{p.ticker}</td>
                  <td>{p.direction}</td>
                  <td className="mono">{fmtPrice(p.price)}</td>
                  <td className="mono">{fmtPrice(p.adv_lo)}</td>
                  <td className="mono">{fmtPrice(p.adv_mid)}</td>
                  <td className="mono">{fmtPrice(p.adv_hi)}</td>
                  <td className="mono">
                    {p.ev_score != null ? `${p.ev_score.toFixed(1)}%` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="ml-note" style={{ marginTop: 16 }}>
        Favourable upside bands stay on <a href="/ml/ranges">Predicted Ranges</a>.
        Fib stops are unchanged — this is a parallel risk estimate (
        {runs.length} logged runs).
      </div>
    </>
  );
}
