"use client";

import { useState } from "react";
import type { ScanGroup } from "@/lib/types";
import PickCard from "./PickCard";

export default function ScanSection({
  group,
  defaultExpanded = false,
}: {
  group: ScanGroup;
  defaultExpanded?: boolean;
}) {
  const [open, setOpen] = useState(defaultExpanded);

  return (
    <section className={`scan-block${open ? " expanded" : " collapsed"}`}>
      <button
        type="button"
        className="scan-block-header"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <div className="scan-block-header-left">
          <span className="hour-pill">{group.et_time} ET</span>
          {group.trade_run && <span className="trade-tag">TRADE WINDOW</span>}
          {!open && (
            <span className="scan-block-summary">
              {group.bulls.length} bull · {group.bears.length} bear
            </span>
          )}
        </div>
        <span className="scan-block-chevron" aria-hidden>
          {open ? "▾" : "▸"}
        </span>
      </button>

      {open && (
        <div className="scan-block-body">
          <div className="section-header" style={{ marginTop: 0 }}>
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
        </div>
      )}
    </section>
  );
}
