import { getLatestBoostedRun, getBoostedRuns } from "@/lib/boosted-queries";
import type { BoostedRunRow, BoostedImportanceItem } from "@/lib/types";
import MlMetricHistoryChart from "@/components/MlMetricHistoryChart";

export const revalidate = 60;

function fmt(n: number | null | undefined, digits = 1, suffix = ""): string {
  if (n == null) return "—";
  return `${n.toFixed(digits)}${suffix}`;
}

function ImportanceTable({ items }: { items: BoostedImportanceItem[] }) {
  const top = items.slice(0, 10);
  const max = Math.max(...top.map((i) => i.gain), 1);
  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <div className="panel-title">Feature importance (gain)</div>
      <table className="data-table">
        <thead>
          <tr>
            <th>Feature</th>
            <th>Gain</th>
            <th style={{ width: "40%" }}></th>
          </tr>
        </thead>
        <tbody>
          {top.map((item) => (
            <tr key={item.name}>
              <td className="mono">{item.name}</td>
              <td className="mono">{item.gain.toFixed(1)}</td>
              <td>
                <div className="conviction-bar-bg" style={{ height: 6 }}>
                  <div
                    className="conviction-fill bull"
                    style={{ width: `${(100 * item.gain) / max}%` }}
                  />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function BoostedPhitPage() {
  let latest: BoostedRunRow | null = null;
  let runs: BoostedRunRow[] = [];
  let err: string | null = null;
  try {
    [latest, runs] = await Promise.all([
      getLatestBoostedRun(),
      getBoostedRuns(50),
    ]);
  } catch (e) {
    err = e instanceof Error ? e.message : String(e);
  }

  if (err) {
    return (
      <>
        <div className="topbar">
          <div>
            <div className="page-title">Boosted P(hit)</div>
            <div className="page-sub">Connection error</div>
          </div>
        </div>
        <div className="error-box">
          Could not load boosted runs from Supabase: <code>{err}</code>
        </div>
      </>
    );
  }

  if (!latest) {
    return (
      <>
        <div className="topbar">
          <div>
            <div className="page-title">Boosted P(hit)</div>
            <div className="page-sub">
              LightGBM gradient-boosted Fib-hit classifier
            </div>
          </div>
        </div>
        <div className="empty-state">
          <div className="icon">🌲</div>
          <p>No boosted model runs logged yet.</p>
          <p className="hint">
            Run{" "}
            <code>python -m backtest.boosted_tuner --save-db</code> to train
            the LightGBM P(hit) + price-range models. The classic logistic Fib
            pipeline on <code>/ml</code> is unchanged.
          </p>
        </div>
      </>
    );
  }

  const history = runs
    .slice()
    .reverse()
    .map((r) => ({
      label: `${r.trade_date ?? ""} ${r.et_time ?? ""}`.trim() || `#${r.id}`,
      auc:
        r.phit_test_auc == null
          ? null
          : Math.round(r.phit_test_auc * 1000) / 10,
      acc: r.phit_test_acc ?? null,
    }));

  const bias = latest.selection_bias;
  const importance = latest.phit_importance ?? [];

  return (
    <>
      <div className="topbar">
        <div>
          <div className="page-title">Boosted P(hit)</div>
          <div className="page-sub">
            LightGBM gradient boosting · run #{latest.id} ·{" "}
            {latest.trade_date} {latest.et_time} ET · source {latest.source}
          </div>
        </div>
        <span className="ml-flag">parallel to logistic · does not change weights</span>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-label">Walk-forward AUC</div>
          <div className="stat-value bull">{fmt(latest.phit_test_auc, 3)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Test accuracy</div>
          <div className="stat-value">{fmt(latest.phit_test_acc, 1, "%")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Samples</div>
          <div className="stat-value">{latest.phit_n_samples ?? "—"}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Base hit rate</div>
          <div className="stat-value">{fmt(latest.phit_base_rate, 1, "%")}</div>
        </div>
      </div>

      {bias && (
        <div className="ml-note" style={{ marginTop: 12 }}>
          Selection bias: picks {fmt(bias.pick_hit_rate, 1, "%")} (n=
          {bias.n_pick}) vs rejected {fmt(bias.nonpick_hit_rate, 1, "%")} (n=
          {bias.n_nonpick})
        </div>
      )}

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-title">AUC / accuracy over runs</div>
        <MlMetricHistoryChart data={history} />
      </div>

      {importance.length > 0 && <ImportanceTable items={importance} />}

      <div className="ml-note" style={{ marginTop: 16 }}>
        Retrain weekly with{" "}
        <code>python -m backtest.boosted_tuner --save-db</code>. Logistic
        conviction weights and Fib targets stay on{" "}
        <a href="/ml">Model Weights</a>.
      </div>
    </>
  );
}
