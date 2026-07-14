import { getFeatureDatasetStats } from "@/lib/ml-queries";
import type { FeatureDatasetStats } from "@/lib/types";

export const revalidate = 60;

function pct(n: number | null): string {
  return n == null ? "—" : `${n}%`;
}

export default async function MlDataPage() {
  let stats: FeatureDatasetStats | null = null;
  let err: string | null = null;
  try {
    stats = await getFeatureDatasetStats();
  } catch (e) {
    err = e instanceof Error ? e.message : String(e);
  }

  if (err) {
    return (
      <>
        <div className="topbar">
          <div>
            <div className="page-title">Training Data</div>
            <div className="page-sub">Connection error</div>
          </div>
        </div>
        <div className="error-box">
          Could not load training data from Supabase: <code>{err}</code>
        </div>
      </>
    );
  }

  const s = stats!;
  const unlabeled = Math.max(0, s.total - s.labeled);
  const edgeGap =
    s.pick_hit_pct != null && s.nonpick_hit_pct != null
      ? s.pick_hit_pct - s.nonpick_hit_pct
      : null;

  return (
    <>
      <div className="topbar">
        <div>
          <div className="page-title">Training Data</div>
          <div className="page-sub">
            Full scanned universe logged to <code>scan_features</code> — the
            de-biased dataset the weight learner trains on
          </div>
        </div>
      </div>

      {s.total === 0 ? (
        <div className="empty-state">
          <div className="icon">🗄️</div>
          <p>No universe features logged yet.</p>
          <p className="hint">
            Every scheduled scan now writes all analyzed tickers here (not just
            top picks). Rows get labeled at the 4 PM ET validation. Check back
            after a scan day.
          </p>
        </div>
      ) : (
        <>
          <div className="stats-row">
            <div className="stat-card">
              <div className="stat-label">Total Rows Logged</div>
              <div className="stat-value">{s.total.toLocaleString()}</div>
              <div className="stat-sub">
                across {s.days} trading day{s.days === 1 ? "" : "s"}
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Labeled (fib validated)</div>
              <div className="stat-value">{s.labeled.toLocaleString()}</div>
              <div className="stat-sub">{unlabeled.toLocaleString()} pending</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Overall Hit Rate</div>
              <div className="stat-value">{pct(s.hit_pct)}</div>
              <div className="stat-sub">
                {s.hits.toLocaleString()} / {s.labeled.toLocaleString()}
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Date Range</div>
              <div className="stat-value" style={{ fontSize: 15 }}>
                {s.first_date ?? "—"} → {s.last_date ?? "—"}
              </div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-title">
              Selection Bias · why we log the whole universe
            </div>
            <p className="ml-note">
              Training only on surfaced picks was biased — the model never saw the
              setups the scanner rejected, so it couldn&apos;t learn what separates
              good from bad. Now we record both. If picks out-hit the rejected
              universe, the ranking has real edge; either way the model gets a fair,
              de-biased dataset.
            </p>
            <div className="stats-row" style={{ marginBottom: 0 }}>
              <div className="stat-card">
                <div className="stat-label">Surfaced Picks</div>
                <div className="stat-value bull">{pct(s.pick_hit_pct)}</div>
                <div className="stat-sub">
                  {s.picks.toLocaleString()} labeled rows
                </div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Rejected Universe</div>
                <div className="stat-value bear">{pct(s.nonpick_hit_pct)}</div>
                <div className="stat-sub">
                  {s.nonpicks.toLocaleString()} labeled rows
                </div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Edge Gap</div>
                <div className="stat-value accent">
                  {edgeGap == null ? "—" : `${edgeGap.toFixed(0)} pts`}
                </div>
                <div className="stat-sub">picks − rejected</div>
              </div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-title">How the pipeline works</div>
            <ol className="ml-steps">
              <li>
                Each scheduled scan scores every ticker and writes its 10-signal
                vector + context to <code>scan_features</code> (
                <code>was_pick</code> flags the top-N).
              </li>
              <li>
                At 4 PM ET the validator labels each row with{" "}
                <code>fib_hit</code> — did price reach the next-hour Fibonacci
                target.
              </li>
              <li>
                <code>backtest.logistic_tuner</code> reads the labeled rows, adds
                market-regime features, and fits an L2 logistic regression.
              </li>
              <li>
                The learned signal weights are written to{" "}
                <code>conviction.py</code>; the run is logged for the Model tab.
              </li>
            </ol>
          </div>
        </>
      )}
    </>
  );
}
