import { getTodayPicks, groupByScan, topConvictionByHour } from "@/lib/queries";
import ScanSection from "@/components/ScanSection";
import ConvictionChart from "@/components/ConvictionChart";
import type { PickRow } from "@/lib/types";

// Always fetch fresh; new scans land hourly.
export const revalidate = 60;

export default async function TodayPage() {
  let picks: PickRow[] = [];
  let err: string | null = null;
  try {
    picks = await getTodayPicks();
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
          <p className="hint">The scanner writes here each hour from 9:35 AM to 3:35 PM ET.</p>
        </div>
      ) : (
        <>
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

          {groups.map((g) => (
            <ScanSection key={g.scan_id} group={g} />
          ))}
        </>
      )}
    </>
  );
}
