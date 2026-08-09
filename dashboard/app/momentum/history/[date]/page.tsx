import Link from "next/link";
import { getMomentumDayPicks, groupMomentumByScan } from "@/lib/momentum-queries";
import MomentumScanSection from "@/components/MomentumScanSection";
import FibHitSummary from "@/components/FibHitSummary";
import type { MomentumPickRow, FibHitStats } from "@/lib/types";

export const revalidate = 60;

function hitStatsFromPicks(picks: MomentumPickRow[]): FibHitStats | null {
  const withTarget = picks.filter((p) => p.day_target != null);
  if (withTarget.length === 0) return null;
  const validatedRows = withTarget.filter((p) => p.target_hit != null);
  if (validatedRows.length === 0) return null;
  const hits = validatedRows.filter((p) => p.target_hit === true).length;
  const misses = validatedRows.filter((p) => p.target_hit === false).length;
  const unknown = withTarget.length - validatedRows.length;
  return {
    hits,
    misses,
    unknown,
    validated: validatedRows.length,
    with_target: withTarget.length,
    hit_pct: validatedRows.length
      ? Math.round((hits / validatedRows.length) * 1000) / 10
      : 0,
  };
}

export default async function MomentumDayPage({ params }: { params: { date: string } }) {
  const { date } = params;
  let picks: MomentumPickRow[] = [];
  let err: string | null = null;
  try {
    picks = await getMomentumDayPicks(date);
  } catch (e) {
    err = e instanceof Error ? e.message : String(e);
  }

  const groups = groupMomentumByScan(picks);
  const fibStats = hitStatsFromPicks(picks);

  return (
    <>
      <Link href="/momentum/history" className="back-link">← All days</Link>
      <div className="topbar">
        <div>
          <div className="page-title">{date}</div>
          <div className="page-sub">
            {groups.length} scan{groups.length === 1 ? "" : "s"} this day
          </div>
        </div>
      </div>

      {err ? (
        <div className="error-box">Could not load this day: <code>{err}</code></div>
      ) : groups.length === 0 ? (
        <div className="empty-state">
          <div className="icon">📭</div>
          <p>No momentum picks recorded for {date}.</p>
        </div>
      ) : (
        <>
          {fibStats && (
            <FibHitSummary
              stats={fibStats}
              label="that day"
              title="Day Target Accuracy · entry then target before stop · validated after 4 PM ET"
            />
          )}

          {groups.map((g, i) => (
            <MomentumScanSection key={g.scan_id} group={g} defaultExpanded={i === 0} />
          ))}
        </>
      )}
    </>
  );
}
