"use client";

import { useState } from "react";
import type { MomentumScanGroup } from "@/lib/types";
import MomentumPickCard from "./MomentumPickCard";

export default function MomentumScanSection({
  group,
  defaultExpanded = false,
}: {
  group: MomentumScanGroup;
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
          {group.mode && <span className="trade-tag">{group.mode.toUpperCase()}</span>}
          {!open && (
            <span className="scan-block-summary">
              {group.longs.length} LONG · {group.shorts.length} SHORT
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
              {group.longs.length} LONG · {group.shorts.length} SHORT
              {group.universe ? ` · ${group.universe}` : ""}
            </span>
          </div>

          {group.longs.length > 0 && (
            <>
              <div className="section-title" style={{ marginBottom: 8 }}>
                ▲ Top {group.longs.length} Longs
              </div>
              <div className="picks-grid">
                {group.longs.map((p) => (
                  <MomentumPickCard key={`${p.scan_id}-long-${p.ticker}`} pick={p} />
                ))}
              </div>
            </>
          )}

          {group.shorts.length > 0 && (
            <>
              <div className="section-title" style={{ margin: "12px 0 8px" }}>
                ▼ Top {group.shorts.length} Shorts
              </div>
              <div className="picks-grid">
                {group.shorts.map((p) => (
                  <MomentumPickCard key={`${p.scan_id}-short-${p.ticker}`} pick={p} />
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
