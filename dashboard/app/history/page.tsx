import Link from "next/link";
import { getDays } from "@/lib/queries";
import type { DaySummary } from "@/lib/types";

export const revalidate = 60;

export default async function HistoryPage() {
  let days: DaySummary[] = [];
  let err: string | null = null;
  try {
    days = await getDays();
  } catch (e) {
    err = e instanceof Error ? e.message : String(e);
  }

  return (
    <>
      <div className="topbar">
        <div>
          <div className="page-title">History</div>
          <div className="page-sub">Pick a day to drill into its hourly scans</div>
        </div>
      </div>

      {err ? (
        <div className="error-box">Could not load days: <code>{err}</code></div>
      ) : days.length === 0 ? (
        <div className="empty-state">
          <div className="icon">🗓</div>
          <p>No scans recorded yet.</p>
        </div>
      ) : (
        <div className="day-grid">
          {days.map((d) => (
            <Link key={d.trade_date} href={`/history/${d.trade_date}`} className="day-card">
              <div className="day-date">{d.trade_date}</div>
              <div className="day-meta">
                {d.scan_count} scan{d.scan_count === 1 ? "" : "s"} · last {d.last_et_time} ET
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
