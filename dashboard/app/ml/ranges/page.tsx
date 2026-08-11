import {
  getLatestBoostedRun,
  getBoostedRuns,
  getRecentRangePicks,
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

export default async function PriceRangesPage() {
  let latest: BoostedRunRow | null = null;
  let runs: BoostedRunRow[] = [];
  let picks: PickRow[] = [];
  let err: string | null = null;
  try {
    [latest, runs, picks] = await Promise.all([
      getLatestBoostedRun(),
      getBoostedRuns(20),
      getRecentRangePicks(30),
    ]);
  } catch (e) {
    err = e instanceof Error ? e.message : String(e);
  }

  if (err) {
    return (
      <>
        <div className="topbar">
          <div>
            <div className="page-title">Predicted Ranges</div>
            <div className="page-sub">Connection error</div>
          </div>
        </div>
        <div className="error-box">
          Could not load range model data: <code>{err}</code>
        </div>
      </>
    );
  }

  if (!latest || latest.range_n_samples == null) {
    return (
      <>
        <div className="topbar">
          <div>
            <div className="page-title">Predicted Ranges</div>
            <div className="page-sub">
              LightGBM quantile regression of favourable Fib-window move
            </div>
          </div>
        </div>
        <div className="empty-state">
          <div className="icon">📐</div>
          <p>No price-range model logged yet.</p>
          <p className="hint">
            Run <code>python -m backtest.boosted_tuner --save-db</code>. Needs
            labeled rows with <code>fib_window_high</code> /{" "}
            <code>fib_window_low</code> from the 4 PM validator.
          </p>
        </div>
      </>
    );
  }

  const coverage = latest.range_test_coverage ?? {};
  const mae = latest.range_test_mae ?? {};
  const importance = latest.range_importance ?? [];

  return (
    <>
      <div className="topbar">
        <div>
          <div className="page-title">Predicted Ranges</div>
          <div className="page-sub">
            Quantile excursion model · run #{latest.id} · {latest.trade_date}{" "}
            {latest.et_time} ET
          </div>
        </div>
        <span className="ml-flag">parallel to Fib targets · does not replace them</span>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-label">Training rows</div>
          <div className="stat-value">{latest.range_n_samples ?? "—"}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Mean excursion</div>
          <div className="stat-value">
            {fmt(latest.range_mean_excursion, 2, "%")}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Median excursion</div>
          <div className="stat-value">
            {fmt(latest.range_median_excursion, 2, "%")}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Runs logged</div>
          <div className="stat-value">{runs.length}</div>
        </div>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-title">Walk-forward quantile check</div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Quantile</th>
              <th>Ideal coverage</th>
              <th>Observed</th>
              <th>MAE (excursion)</th>
            </tr>
          </thead>
          <tbody>
            {["0.25", "0.50", "0.75"].map((q) => (
              <tr key={q}>
                <td className="mono">q{q}</td>
                <td className="mono">{q}</td>
                <td className="mono">
                  {coverage[q] != null ? coverage[q].toFixed(3) : "—"}
                </td>
                <td className="mono">
                  {mae[q] != null ? mae[q].toFixed(4) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="ml-note" style={{ marginTop: 8 }}>
          Coverage near 0.25 / 0.50 / 0.75 means the bands are well calibrated.
        </p>
      </div>

      {importance.length > 0 && (
        <div className="panel" style={{ marginTop: 16 }}>
          <div className="panel-title">Top features (median model)</div>
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
        <div className="panel-title">
          Recent picks with predicted bands
        </div>
        {picks.length === 0 ? (
          <p className="ml-note">
            No picks with <code>pred_mid</code> yet — next scan after training
            will fill these in.
          </p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Ticker</th>
                <th>Dir</th>
                <th>Price</th>
                <th>Pred lo</th>
                <th>Pred mid</th>
                <th>Pred hi</th>
                <th>Boosted P(hit)</th>
                <th>Fib target</th>
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
                  <td className="mono">{fmtPrice(p.pred_lo)}</td>
                  <td className="mono">{fmtPrice(p.pred_mid)}</td>
                  <td className="mono">{fmtPrice(p.pred_hi)}</td>
                  <td className="mono">
                    {p.xgb_phit != null
                      ? `${(p.xgb_phit * 100).toFixed(0)}%`
                      : "—"}
                  </td>
                  <td className="mono">{fmtPrice(p.fib_target)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
