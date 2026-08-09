import type { FibHitStats } from "@/lib/types";

export default function FibHitSummary({
  stats,
  label = "today",
  title = "Fib Target Accuracy · validated after 4 PM ET",
}: {
  stats: FibHitStats;
  label?: "today" | "that day";
  title?: string;
}) {
  const dayLabel = label === "today" ? "today" : "that day";

  return (
    <div className="fib-summary panel">
      <div className="panel-title">{title}</div>
      <div className="stats-row" style={{ marginBottom: 0 }}>
        <div className="stat-card fib-stat-main">
          <div className="stat-label">Hit Rate</div>
          <div className="stat-value bull">
            {stats.hits}/{stats.validated}
          </div>
          <div className="stat-sub">{stats.hit_pct}% correct {dayLabel}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Hits</div>
          <div className="stat-value bull">{stats.hits}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Misses</div>
          <div className="stat-value bear">{stats.misses}</div>
        </div>
        {stats.unknown > 0 && (
          <div className="stat-card">
            <div className="stat-label">No Bar Data</div>
            <div className="stat-value">{stats.unknown}</div>
          </div>
        )}
        <div className="stat-card">
          <div className="stat-label">With Fib Target</div>
          <div className="stat-value">{stats.with_target}</div>
        </div>
      </div>
    </div>
  );
}
