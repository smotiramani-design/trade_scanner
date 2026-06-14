import Link from "next/link";
import { getDayPicks, groupByScan } from "@/lib/queries";
import ScanSection from "@/components/ScanSection";
import type { PickRow } from "@/lib/types";

export const revalidate = 60;

export default async function DayPage({ params }: { params: { date: string } }) {
  const { date } = params;
  let picks: PickRow[] = [];
  let err: string | null = null;
  try {
    picks = await getDayPicks(date);
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
        groups.map((g) => <ScanSection key={g.scan_id} group={g} />)
      )}
    </>
  );
}
