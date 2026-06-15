import Link from "next/link";
import { getMomentumDays } from "@/lib/momentum-queries";
import type { MomentumDaySummary } from "@/lib/types";

export const revalidate = 60;

export default async function MomentumHistoryPage() {
  let days: MomentumDaySummary[] = [];
  let err: string | null = null;
  try {
    days = await getMomentumDays();
  } catch (e) {
    err = e instanceof Error ? e.message : String(e);
  }

  return (
    <>
      <div className="topbar">
        <div>
          <div className="page-title">Historical Scans</div>
          <div className="page-sub">Pick a day to drill into its daily run</div>
        </div>
      </div>

      {err ? (
        <div className="error-box">Could not load days: <code>{err}</code></div>
      ) : days.length === 0 ? (
        <div className="empty-state">
          <div className="icon">🗓</div>
          <p>No momentum scans recorded yet.</p>
        </div>
      ) : (
        <div className="day-grid">
          {days.map((d) => (
            <Link
              key={d.trade_date}
              href={`/momentum/history/${d.trade_date}`}
              className="day-card"
            >
              <div className="day-date">{d.trade_date}</div>
              <div className="day-meta">
                {d.n_trade} TRADE · {d.n_watch} WATCH · {d.et_time} ET
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
