import Link from "next/link";
import {
  getTodayMomentumPicks,
  groupMomentumByScan,
  topMomentumConviction,
} from "@/lib/momentum-queries";
import MomentumScanSection from "@/components/MomentumScanSection";
import type { MomentumPickRow } from "@/lib/types";

export const revalidate = 60;

export default async function MomentumTodayPage() {
  let picks: MomentumPickRow[] = [];
  let err: string | null = null;
  try {
    picks = await getTodayMomentumPicks();
  } catch (e) {
    err = e instanceof Error ? e.message : String(e);
  }

  if (err) {
    return (
      <>
        <div className="topbar">
          <div>
            <div className="page-title">Momentum</div>
            <div className="page-sub">Connection error</div>
          </div>
        </div>
        <div className="error-box">
          Could not load momentum data from Supabase: <code>{err}</code>
        </div>
      </>
    );
  }

  const groups = groupMomentumByScan(picks);
  const latest = groups[0];
  const tradeCount = picks.filter((p) => p.tier === "TRADE").length;
  const watchCount = picks.filter((p) => p.tier === "WATCH").length;
  const top = topMomentumConviction(picks);

  return (
    <>
      <div className="topbar">
        <div>
          <div className="page-title">Momentum</div>
          <div className="page-sub">
            {latest
              ? `Today's run ${latest.et_time} ET · pre-market screener`
              : "No run yet today"}
          </div>
        </div>
        <Link href="/momentum/history" className="back-link" style={{ marginBottom: 0 }}>
          History →
        </Link>
      </div>

      {picks.length === 0 ? (
        <div className="empty-state">
          <div className="icon">📭</div>
          <p>No momentum picks recorded today yet.</p>
          <p className="hint">The screener runs at 9:15 AM ET Mon–Fri.</p>
        </div>
      ) : (
        <>
          <div className="stats-row">
            <div className="stat-card">
              <div className="stat-label">TRADE</div>
              <div className="stat-value bull">{tradeCount}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">WATCH</div>
              <div className="stat-value accent">{watchCount}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Total Movers</div>
              <div className="stat-value">{picks.length}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Top Conviction</div>
              <div className="stat-value">
                {top ? `${top.ticker} ${top.conviction.toFixed(0)}` : "—"}
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
