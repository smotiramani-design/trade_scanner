import Link from "next/link";
import {
  getDayPicks,
  groupByScan,
  getFibHitStats,
  isPastFibValidationTime,
} from "@/lib/queries";
import ScanSection from "@/components/ScanSection";
import FibHitSummary from "@/components/FibHitSummary";
import type { PickRow, FibHitStats } from "@/lib/types";

export const revalidate = 60;

export default async function DayPage({ params }: { params: { date: string } }) {
  const { date } = params;
  let picks: PickRow[] = [];
  let fibStats: FibHitStats | null = null;
  let err: string | null = null;
  try {
    picks = await getDayPicks(date);
    if (isPastFibValidationTime(date)) {
      fibStats = await getFibHitStats(date);
    }
  } catch (e) {
    err = e instanceof Error ? e.message : String(e);
  }

  const groups = groupByScan(picks);

  return (
    <>
      <Link href="/history" className="back-link">← All days</Link>
      <div className="topbar">
        <div>
          <div className="page-title">{date}</div>
          <div className="page-sub">{groups.length} scans this day</div>
        </div>
      </div>

      {err ? (
        <div className="error-box">Could not load this day: <code>{err}</code></div>
      ) : groups.length === 0 ? (
        <div className="empty-state">
          <div className="icon">📭</div>
          <p>No picks recorded for {date}.</p>
        </div>
      ) : (
        <>
          {fibStats && <FibHitSummary stats={fibStats} label="that day" />}

          {groups.map((g, i) => (
            <ScanSection key={g.scan_id} group={g} defaultExpanded={i === 0} />
          ))}
        </>
      )}
    </>
  );
}
