import type { MomentumPickRow } from "@/lib/types";

function fmtPrice(n: number | null) {
  return n == null ? "—" : `$${n.toFixed(2)}`;
}
function fmtChg(n: number | null) {
  if (n == null) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function scoreDots(score: number | null) {
  const s = score ?? 0;
  return (
    <span className="score-dots" aria-label={`Score ${s} of 5`}>
      {Array.from({ length: 5 }, (_, i) => (
        <span key={i} className={`score-dot${i < s ? " on" : ""}`} />
      ))}
    </span>
  );
}

export default function MomentumPickCard({ pick }: { pick: MomentumPickRow }) {
  const isTrade = pick.tier === "TRADE";
  const conviction = pick.conviction ?? 0;
  const chgUp = (pick.pm_change_pct ?? 0) >= 0;
  const cardClass = isTrade ? "trade-card" : "watch-card";

  return (
    <div className={`pick-card ${cardClass}`}>
      <div className="card-head">
        <div>
          <div className="card-ticker">{pick.ticker}</div>
          <div className="card-name">{pick.company ?? pick.sector ?? ""}</div>
        </div>
        <div>
          <div className="card-price">{fmtPrice(pick.pm_price)}</div>
          <div className={`card-chg ${chgUp ? "up" : "down"}`}>{fmtChg(pick.pm_change_pct)}</div>
        </div>
      </div>

      <div className="card-body">
        <div className="conviction-row">
          <span className="conviction-label">{isTrade ? "Conviction" : "Score"}</span>
          <div className="conviction-bar-bg">
            <div
              className={`conviction-fill ${isTrade ? "bull" : "watch"}`}
              style={{
                width: `${Math.min(100, Math.max(0, isTrade ? (conviction / 88) * 100 : ((pick.score ?? 0) / 5) * 100))}%`,
              }}
            />
          </div>
          <span className="conviction-pct">
            {isTrade ? conviction.toFixed(0) : `${pick.score ?? 0}/5`}
          </span>
        </div>

        <div className="card-row">
          <span className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>
            {pick.rank != null ? `#${pick.rank} · ` : ""}
            gap {fmtChg(pick.gap_pct)}
          </span>
          <span className={`tier-badge ${pick.tier.toLowerCase()}`}>{pick.tier}</span>
        </div>

        {scoreDots(pick.score)}

        <div className="layer-rows">
          {pick.l1_catalyst && (
            <div className="layer-row">
              <label>L1</label>
              <span>{pick.l1_catalyst}</span>
            </div>
          )}
          {pick.l2_volume && (
            <div className="layer-row">
              <label>L2</label>
              <span>{pick.l2_volume}</span>
            </div>
          )}
          {pick.l3_price && (
            <div className="layer-row">
              <label>L3</label>
              <span>{pick.l3_price}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
