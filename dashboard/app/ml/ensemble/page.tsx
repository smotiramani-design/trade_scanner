import {
  getLatestBoostedRun,
  getBoostedRuns,
  getRecentEnsemblePicks,
} from "@/lib/boosted-queries";
import type { BoostedRunRow, PickRow } from "@/lib/types";
import MlMetricHistoryChart from "@/components/MlMetricHistoryChart";

export const revalidate = 60;

function fmt(n: number | null | undefined, digits = 1, suffix = ""): string {
  if (n == null) return "—";
  return `${n.toFixed(digits)}${suffix}`;
}

function pct(n: number | null | undefined) {
  if (n == null) return "—";
  return `${(n * 100).toFixed(0)}%`;
}

export default async function EnsemblePhitPage() {
  let latest: BoostedRunRow | null = null;
  let runs: BoostedRunRow[] = [];
  let picks: PickRow[] = [];
  let err: string | null = null;
  try {
    [latest, runs, picks] = await Promise.all([
      getLatestBoostedRun(),
      getBoostedRuns(50),
      getRecentEnsemblePicks(30),
    ]);
  } catch (e) {
    err = e instanceof Error ? e.message : String(e);
  }

  if (err) {
    return (
      <>
        <div className="topbar">
          <div>
            <div className="page-title">Ensemble P(hit)</div>
            <div className="page-sub">Connection error</div>
          </div>
        </div>
        <div className="error-box">
          Could not load ensemble data: <code>{err}</code>
        </div>
      </>
    );
  }

  if (!latest) {
    return (
      <>
        <div className="topbar">
          <div>
            <div className="page-title">Ensemble P(hit)</div>
            <div className="page-sub">
              Average of logistic + LightGBM + XGBoost hit probabilities
            </div>
          </div>
        </div>
        <div className="empty-state">
          <div className="icon">🧮</div>
          <p>No boosted model runs logged yet.</p>
          <p className="hint">
            Run <code>python -m backtest.boosted_tuner --save-db</code> to train
            LightGBM + XGBoost. Ensemble blends those with logistic P(hit) at
            scan time.
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
        r.xgb_test_auc != null
          ? Math.round(r.xgb_test_auc * 1000) / 10
          : r.phit_test_auc == null
            ? null
            : Math.round(r.phit_test_auc * 1000) / 10,
      acc: r.xgb_test_acc ?? r.phit_test_acc ?? null,
    }));

  const xgbImp = latest.xgb_importance ?? [];

  return (
    <>
      <div className="topbar">
        <div>
          <div className="page-title">Ensemble P(hit)</div>
          <div className="page-sub">
            Logistic + LightGBM + XGBoost · run #{latest.id} ·{" "}
            {latest.trade_date} {latest.et_time} ET
          </div>
        </div>
        <span className="ml-flag">parallel · does not change pick ranking</span>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-label">LightGBM AUC</div>
          <div className="stat-value bull">{fmt(latest.phit_test_auc, 3)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">XGBoost AUC</div>
          <div className="stat-value bull">{fmt(latest.xgb_test_auc, 3)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">XGB test acc</div>
          <div className="stat-value">{fmt(latest.xgb_test_acc, 1, "%")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Samples</div>
          <div className="stat-value">{latest.phit_n_samples ?? "—"}</div>
        </div>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-title">How the blend works</div>
        <p style={{ padding: "8px 12px", margin: 0, color: "var(--muted)", fontSize: 14 }}>
          At scan time <code>ens_phit</code> is the simple average of whichever
          are available: logistic <code>phit</code>, LightGBM (
          <code>xgb_phit</code>), and true XGBoost (<code>xgboost_phit</code>).
          EV score pairs ensemble hit-prob with favourable vs adverse mid
          excursions.
        </p>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-title">XGBoost AUC / accuracy over runs</div>
        <MlMetricHistoryChart data={history} />
      </div>

      {xgbImp.length > 0 && (
        <div className="panel" style={{ marginTop: 16 }}>
          <div className="panel-title">XGBoost feature importance</div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Feature</th>
                <th>Gain</th>
              </tr>
            </thead>
            <tbody>
              {xgbImp.slice(0, 10).map((item) => (
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
        <div className="panel-title">Recent picks with ensemble scores</div>
        {picks.length === 0 ? (
          <p className="hint" style={{ padding: 12 }}>
            No picks with <code>ens_phit</code> yet — next scan after training
            will populate them.
          </p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Ticker</th>
                <th>Dir</th>
                <th>Logistic</th>
                <th>LightGBM</th>
                <th>XGBoost</th>
                <th>Ensemble</th>
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
                  <td className="mono">{pct(p.phit)}</td>
                  <td className="mono">{pct(p.xgb_phit)}</td>
                  <td className="mono">{pct(p.xgboost_phit)}</td>
                  <td className="mono">{pct(p.ens_phit)}</td>
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
        Retrain with <code>python -m backtest.boosted_tuner --save-db</code>.
        Ranking still uses logistic P(hit) / conviction on{" "}
        <a href="/ml">Model Weights</a>.
      </div>
    </>
  );
}
