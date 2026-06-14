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
          {group.session && <span className="trade-tag">{group.session.toUpperCase()}</span>}
          {!open && (
            <span className="scan-block-summary">
              {group.trade.length} TRADE · {group.watch.length} WATCH
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
              {group.trade.length} TRADE · {group.watch.length} WATCH
              {group.universe ? ` · ${group.universe}` : ""}
            </span>
          </div>

          {group.trade.length > 0 && (
            <>
              <div className="section-title" style={{ marginBottom: 8 }}>TRADE</div>
              <div className="picks-grid">
                {group.trade.map((p) => (
                  <MomentumPickCard key={`${p.scan_id}-trade-${p.ticker}`} pick={p} />
                ))}
              </div>
            </>
          )}

          {group.watch.length > 0 && (
            <>
              <div className="section-title" style={{ margin: "12px 0 8px" }}>WATCH</div>
              <div className="picks-grid">
                {group.watch.map((p) => (
                  <MomentumPickCard key={`${p.scan_id}-watch-${p.ticker}`} pick={p} />
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
