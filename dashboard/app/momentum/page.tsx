import {
  getTodayMomentumPicks,
  getMomentumHitStats,
  aggregateHitStats,
  groupMomentumByScan,
  topMomentumConviction,
} from "@/lib/momentum-queries";
import MomentumScanSection from "@/components/MomentumScanSection";
import StrategyKey from "@/components/StrategyKey";
import type { MomentumPickRow, MomentumHitStats } from "@/lib/types";

export const revalidate = 60;

function pct(n: number | null) {
  return n == null ? "—" : `${n.toFixed(0)}%`;
}

export default async function MomentumTodayPage() {
  let picks: MomentumPickRow[] = [];
  let hitRows: MomentumHitStats[] = [];
  let err: string | null = null;
  try {
    picks = await getTodayMomentumPicks();
  } catch (e) {
    err = e instanceof Error ? e.message : String(e);
  }
  // Hit-rate stats are best-effort: a missing v_momentum_hit_stats view (not yet
  // migrated) must not blank out today's picks.
  try {
    hitRows = await getMomentumHitStats(60);
  } catch {
    hitRows = [];
  }

  if (err) {
    return (
      <>
        <div className="topbar">
          <div>
            <div className="page-title">Daily Scans</div>
            <div className="page-sub">Connection error</div>
          </div>
        </div>
        <div className="error-box">
          Could not load daily scan data from Supabase: <code>{err}</code>
        </div>
      </>
    );
  }

  const groups = groupMomentumByScan(picks);
  const latest = groups[0];
  const longCount = groups.reduce((n, g) => n + g.longs.length, 0);
  const shortCount = groups.reduce((n, g) => n + g.shorts.length, 0);
  const top = topMomentumConviction(picks);
  const stats = aggregateHitStats(hitRows);

  return (
    <>
      <div className="topbar">
        <div>
          <div className="page-title">Daily Scans</div>
          <div className="page-sub">
            {latest
              ? `Today's run ${latest.et_time} ET · Fib + ATR R-plan (daily bars)`
              : "No run yet today"}
          </div>
        </div>
      </div>

      {picks.length === 0 ? (
        <div className="empty-state">
          <div className="icon">📭</div>
          <p>No daily picks recorded today yet.</p>
          <p className="hint">The daily scan runs at 9:15 AM ET Mon–Fri.</p>
        </div>
      ) : (
        <>
          <StrategyKey />

          <div className="stats-row">
            <div className="stat-card">
              <div className="stat-label">Longs</div>
              <div className="stat-value bull">{longCount}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Shorts</div>
              <div className="stat-value bear">{shortCount}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Top Conviction</div>
              <div className="stat-value">
                {top ? `${top.ticker} ${top.conviction.toFixed(0)}%` : "—"}
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-label">
                Target Hit-Rate{stats.days ? ` · ${stats.days}d` : ""}
              </div>
              <div className="stat-value">
                {pct(stats.hitPct)}
                <span className="stat-sub"> ({stats.hits}/{stats.validated})</span>
              </div>
              <div className="stat-sub" style={{ marginTop: 4 }}>
                entry → target before stop
              </div>
            </div>
          </div>

          <div className="stats-row">
            <div className="stat-card">
              <div className="stat-label">Long Hit-Rate</div>
              <div className="stat-value bull">
                {pct(stats.longHitPct)}
                <span className="stat-sub"> ({stats.longHits}/{stats.longValidated})</span>
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Short Hit-Rate</div>
              <div className="stat-value bear">
                {pct(stats.shortHitPct)}
                <span className="stat-sub"> ({stats.shortHits}/{stats.shortValidated})</span>
              </div>
            </div>
          </div>

          {groups.map((g, i) => (
            <MomentumScanSection key={g.scan_id} group={g} defaultExpanded={i === 0} />
          ))}
        </>
      )}
    </>
  );
}
