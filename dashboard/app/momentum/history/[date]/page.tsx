import Link from "next/link";
import { getMomentumDayPicks, groupMomentumByScan } from "@/lib/momentum-queries";
import MomentumScanSection from "@/components/MomentumScanSection";
import type { MomentumPickRow } from "@/lib/types";

export const revalidate = 60;

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
        groups.map((g, i) => (
          <MomentumScanSection key={g.scan_id} group={g} defaultExpanded={i === 0} />
        ))
      )}
    </>
  );
}
