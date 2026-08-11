import {
  getTodayPicks,
  groupByScan,
  topConvictionByHour,
  getFibHitStats,
  getEtTodayDateString,
  isPastFibValidationTime,
} from "@/lib/queries";
import ScanSection from "@/components/ScanSection";
import ConvictionChart from "@/components/ConvictionChart";
import FibHitSummary from "@/components/FibHitSummary";
import StrategyKey from "@/components/StrategyKey";
import type { PickRow, FibHitStats } from "@/lib/types";

// Always fetch fresh; new scans land hourly.
export const revalidate = 60;

export default async function TodayPage() {
  let picks: PickRow[] = [];
  let fibStats: FibHitStats | null = null;
  let err: string | null = null;
  const todayEt = getEtTodayDateString();
  try {
    picks = await getTodayPicks();
    if (isPastFibValidationTime(todayEt)) {
      fibStats = await getFibHitStats(todayEt);
    }
  } catch (e) {
    err = e instanceof Error ? e.message : String(e);
  }

  if (err) {
    return (
      <>
        <div className="topbar">
          <div>
            <div className="page-title">Today</div>
            <div className="page-sub">Connection error</div>
          </div>
        </div>
        <div className="error-box">
          Could not load data from Supabase: <code>{err}</code>
          <br />
          Check <code>NEXT_PUBLIC_SUPABASE_URL</code> / <code>NEXT_PUBLIC_SUPABASE_ANON_KEY</code>{" "}
          and that the <code>anon</code> role can read the views.
        </div>
      </>
    );
  }

  const groups = groupByScan(picks);
  const series = topConvictionByHour(picks);
  const latest = groups[0];
  const bullCount = picks.filter((p) => p.direction === "bull").length;
  const bearCount = picks.filter((p) => p.direction === "bear").length;
  const topPick = picks
    .filter((p) => p.direction === "bull")
    .sort((a, b) => (b.conviction ?? 0) - (a.conviction ?? 0))[0];

  return (
    <>
      <div className="topbar">
        <div>
          <div className="page-title">Today</div>
          <div className="page-sub">
            {latest
              ? `Latest scan ${latest.et_time} ET · ${groups.length} scans today`
              : "No scans yet today"}
          </div>
        </div>
      </div>

      {picks.length === 0 ? (
        <div className="empty-state">
          <div className="icon">📭</div>
          <p>No picks recorded today yet.</p>
          <p className="hint">The scanner writes here each hour from 10:00 AM to 3:00 PM ET.</p>
        </div>
      ) : (
        <>
          {fibStats && (
            <FibHitSummary
              stats={fibStats}
              label="today"
              title="Fib Target Accuracy · entry then target before stop · validated after window close"
            />
          )}

          <StrategyKey />

          <div className="stats-row">
            <div className="stat-card">
              <div className="stat-label">Scans Today</div>
              <div className="stat-value accent">{groups.length}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Bull Picks</div>
              <div className="stat-value bull">{bullCount}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Bear Picks</div>
              <div className="stat-value bear">{bearCount}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Top Conviction</div>
              <div className="stat-value">
                {topPick ? `${topPick.ticker} ${(topPick.conviction ?? 0).toFixed(0)}%` : "—"}
              </div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-title">Top Bullish Conviction by Hour</div>
            <ConvictionChart data={series} />
          </div>

          {groups.map((g, i) => (
            <ScanSection key={g.scan_id} group={g} defaultExpanded={i === 0} />
          ))}
        </>
      )}
    </>
  );
}
