import { getLatestMlRun, getMlRuns } from "@/lib/ml-queries";
import type { MlRunRow, MlWeightItem } from "@/lib/types";
import MlWeightsChart from "@/components/MlWeightsChart";
import MlMetricHistoryChart from "@/components/MlMetricHistoryChart";

export const revalidate = 60;

function fmt(n: number | null | undefined, digits = 1, suffix = ""): string {
  if (n == null) return "—";
  return `${n.toFixed(digits)}${suffix}`;
}

export default async function MlModelPage() {
  let latest: MlRunRow | null = null;
  let runs: MlRunRow[] = [];
  let err: string | null = null;
  try {
    [latest, runs] = await Promise.all([getLatestMlRun(), getMlRuns(50)]);
  } catch (e) {
    err = e instanceof Error ? e.message : String(e);
  }

  if (err) {
    return (
      <>
        <div className="topbar">
          <div>
            <div className="page-title">Model Weights</div>
            <div className="page-sub">Connection error</div>
          </div>
        </div>
        <div className="error-box">
          Could not load ML runs from Supabase: <code>{err}</code>
        </div>
      </>
    );
  }

  if (!latest) {
    return (
      <>
        <div className="topbar">
          <div>
            <div className="page-title">Model Weights</div>
            <div className="page-sub">Logistic-regression conviction weight learning</div>
          </div>
        </div>
        <div className="empty-state">
          <div className="icon">🧠</div>
          <p>No weight-tuning runs logged yet.</p>
          <p className="hint">
            Run <code>python -m backtest.logistic_tuner --save-db</code> to learn
            weights from your labeled scans and populate this tab.
          </p>
        </div>
      </>
    );
  }

  const weights: MlWeightItem[] = latest.weights ?? [];
  const chartData = weights.map((w) => ({
    signal: w.signal,
    old: w.old,
    new: w.new,
  }));
  const contextCoefs = (latest.context_coefs ?? [])
    .slice()
    .sort((a, b) => Math.abs(b.coef) - Math.abs(a.coef));
  const bias = latest.selection_bias;

  // Oldest → newest for the progress chart.
  const history = runs
    .slice()
    .reverse()
    .map((r) => ({
      label: `${r.trade_date ?? ""} ${r.et_time ?? ""}`.trim() || `#${r.id}`,
      auc: r.test_auc == null ? null : Math.round(r.test_auc * 1000) / 10,
      acc: r.test_acc ?? null,
    }));

  return (
    <>
      <div className="topbar">
        <div>
          <div className="page-title">Model Weights</div>
          <div className="page-sub">
            Last run {latest.trade_date ?? "—"} {latest.et_time ?? ""} ET · L2
            logistic regression ·{" "}
            {latest.source === "features"
              ? "full universe (de-biased)"
              : "top picks"}
          </div>
        </div>
        <div>
          <span className={`ml-flag ${latest.applied ? "on" : "off"}`}>
            {latest.applied ? "APPLIED to conviction.py" : "PREVIEW (not applied)"}
          </span>
        </div>
      </div>

      <div className="stats-row">
        <div className="stat-card">
          <div className="stat-label">Walk-forward AUC</div>
          <div className="stat-value bull">{fmt(latest.test_auc, 3)}</div>
          <div className="stat-sub">out-of-sample, time-ordered</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Test Accuracy</div>
          <div className="stat-value">{fmt(latest.test_acc, 1, "%")}</div>
          <div className="stat-sub">{latest.n_test ?? 0} held-out rows</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Base Hit Rate</div>
          <div className="stat-value">{fmt(latest.base_rate, 1, "%")}</div>
          <div className="stat-sub">what beating this means edge</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Training Rows</div>
          <div className="stat-value">{latest.n_samples ?? 0}</div>
          <div className="stat-sub">
            {latest.n_hits ?? 0} hits / {latest.n_misses ?? 0} misses
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-title">Learned vs Hand-tuned Signal Weights</div>
        <MlWeightsChart data={chartData} />
      </div>

      <div className="panel">
        <div className="panel-title">Signal Weights Detail</div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Signal</th>
              <th>Coefficient</th>
              <th>Hand-tuned</th>
              <th>Learned</th>
              <th>Change</th>
            </tr>
          </thead>
          <tbody>
            {weights.map((w) => {
              const change =
                w.new != null && w.old != null ? w.new - w.old : null;
              return (
                <tr key={w.signal}>
                  <td>{w.signal}</td>
                  <td className="mono">{fmt(w.coef, 4)}</td>
                  <td className="mono">{fmt(w.old, 2)}</td>
                  <td className="mono">{fmt(w.new, 2)}</td>
                  <td
                    className={`mono ${
                      change == null ? "" : change > 0 ? "up" : change < 0 ? "down" : ""
                    }`}
                  >
                    {change == null
                      ? "—"
                      : `${change > 0 ? "+" : ""}${change.toFixed(2)}`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {contextCoefs.length > 0 && (
        <div className="panel">
          <div className="panel-title">
            Context &amp; Market-Regime Coefficients · used to de-bias signal weights
          </div>
          <p className="ml-note">
            These features (market trend, momentum, volatility, time-of-day,
            conviction, etc.) enter the model as statistical controls. They aren&apos;t
            written to conviction.py — they make the signal weights above more
            accurate. Positive = pushes toward a hit.
          </p>
          <table className="data-table">
            <thead>
              <tr>
                <th>Feature</th>
                <th>Coefficient</th>
                <th>Effect</th>
              </tr>
            </thead>
            <tbody>
              {contextCoefs.map((c) => (
                <tr key={c.name}>
                  <td className="mono">{c.name}</td>
                  <td
                    className={`mono ${c.coef > 0 ? "up" : c.coef < 0 ? "down" : ""}`}
                  >
                    {fmt(c.coef, 4)}
                  </td>
                  <td>
                    {c.coef > 0 ? "↑ helps hit" : c.coef < 0 ? "↓ hurts" : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {bias && (
        <div className="panel">
          <div className="panel-title">Selection Bias Check · picks vs rejected</div>
          <p className="ml-note">
            Training on the full universe lets us measure this: how the surfaced
            picks actually performed vs the setups the scanner rejected. A gap
            confirms the ranking has real edge (and that picks-only training was
            biased).
          </p>
          <div className="stats-row" style={{ marginBottom: 0 }}>
            <div className="stat-card">
              <div className="stat-label">Surfaced Picks</div>
              <div className="stat-value bull">
                {fmt(bias.pick_hit_rate, 1, "%")}
              </div>
              <div className="stat-sub">{bias.n_pick} labeled rows</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Rejected Universe</div>
              <div className="stat-value bear">
                {fmt(bias.nonpick_hit_rate, 1, "%")}
              </div>
              <div className="stat-sub">{bias.n_nonpick} labeled rows</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Edge Gap</div>
              <div className="stat-value accent">
                {bias.pick_hit_rate != null && bias.nonpick_hit_rate != null
                  ? `${(bias.pick_hit_rate - bias.nonpick_hit_rate).toFixed(1)} pts`
                  : "—"}
              </div>
              <div className="stat-sub">picks − rejected</div>
            </div>
          </div>
        </div>
      )}

      <div className="panel">
        <div className="panel-title">Model Performance Over Time</div>
        <MlMetricHistoryChart data={history} />
      </div>

      <div className="panel">
        <div className="panel-title">Recent Runs</div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Run</th>
              <th>Source</th>
              <th>Rows</th>
              <th>Base</th>
              <th>Test Acc</th>
              <th>AUC</th>
              <th>Regime</th>
              <th>Applied</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <td className="mono">
                  {r.trade_date ?? "—"} {r.et_time ?? ""}
                </td>
                <td>{r.source ?? "—"}</td>
                <td className="mono">{r.n_samples ?? 0}</td>
                <td className="mono">{fmt(r.base_rate, 1, "%")}</td>
                <td className="mono">{fmt(r.test_acc, 1, "%")}</td>
                <td className="mono">{fmt(r.test_auc, 3)}</td>
                <td>{r.use_regime ? "yes" : "no"}</td>
                <td className={r.applied ? "up" : ""}>
                  {r.applied ? "✓" : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
