import type { ScanGroup } from "@/lib/types";
import PickCard from "./PickCard";

export default function ScanSection({ group }: { group: ScanGroup }) {
  return (
    <section>
      <div className="section-header">
        <div>
          <span className="hour-pill">{group.et_time} ET</span>
          {group.trade_run && <span className="trade-tag">TRADE WINDOW</span>}
        </div>
        <span className="section-title">
          {group.bulls.length} bull · {group.bears.length} bear
        </span>
      </div>

      {group.bulls.length > 0 && (
        <>
          <div className="section-title" style={{ marginBottom: 8 }}>Bullish</div>
          <div className="picks-grid">
            {group.bulls.map((p) => (
              <PickCard key={`${p.scan_id}-bull-${p.ticker}`} pick={p} />
            ))}
          </div>
        </>
      )}

      {group.bears.length > 0 && (
        <>
          <div className="section-title" style={{ margin: "12px 0 8px" }}>Bearish</div>
          <div className="picks-grid">
            {group.bears.map((p) => (
              <PickCard key={`${p.scan_id}-bear-${p.ticker}`} pick={p} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}
