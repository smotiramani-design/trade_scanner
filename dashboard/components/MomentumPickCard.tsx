import type { MomentumPickRow } from "@/lib/types";

function fmtPrice(n: number | null) {
  return n == null ? "—" : `$${n.toFixed(2)}`;
}
function fmtChg(n: number | null) {
  if (n == null) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function HitBadge({ hit }: { hit: boolean | null }) {
  if (hit === true) return <span className="tier-badge trade">TARGET HIT</span>;
  if (hit === false) return <span className="tier-badge skip">MISS</span>;
  return <span className="tier-badge watch">PENDING</span>;
}

export default function MomentumPickCard({ pick }: { pick: MomentumPickRow }) {
  const isLong = (pick.direction ?? "bull") === "bull";
  const conviction = pick.conviction ?? 0;
  const chgUp = (pick.chg_pct ?? pick.pm_change_pct ?? 0) >= 0;
  const cardClass = isLong ? "bull-card" : "bear-card";
  const price = pick.price ?? pick.pm_price;
  const chg = pick.chg_pct ?? pick.pm_change_pct;

  return (
    <div className={`pick-card ${cardClass}`}>
      <div className="card-head">
        <div>
          <div className="card-ticker">
            {pick.rank != null ? <span className="mono">#{pick.rank} </span> : null}
            {pick.ticker}
          </div>
          <div className="card-name">{pick.company ?? pick.sector ?? ""}</div>
        </div>
        <div>
          <div className="card-price">{fmtPrice(price)}</div>
          <div className={`card-chg ${chgUp ? "up" : "down"}`}>{fmtChg(chg)}</div>
        </div>
      </div>

      <div className="card-body">
        <div className="card-row">
          <span className={`tier-badge ${isLong ? "trade" : "skip"}`}>
            {isLong ? "LONG" : "SHORT"}
          </span>
          <span className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>
            {pick.grade ? `${pick.grade} · ` : ""}
            {pick.net_score != null
              ? `score ${pick.net_score > 0 ? "+" : ""}${pick.net_score}`
              : ""}
          </span>
        </div>

        <div className="conviction-row">
          <span className="conviction-label">Conviction</span>
          <div className="conviction-bar-bg">
            <div
              className={`conviction-fill ${isLong ? "bull" : "bear"}`}
              style={{ width: `${Math.min(100, Math.max(0, conviction))}%` }}
            />
          </div>
          <span className="conviction-pct">{conviction.toFixed(0)}%</span>
        </div>

        <div className="layer-rows">
          <div className="layer-row">
            <label>Target</label>
            <span>
              {fmtPrice(pick.day_target)}
              {pick.day_target_label ? ` · ${pick.day_target_label}` : ""}
            </span>
          </div>
          <div className="layer-row">
            <label>Entry / Stop</label>
            <span>
              {fmtPrice(pick.fib_entry)} / {fmtPrice(pick.fib_stop)}
            </span>
          </div>
          {(pick.day_high != null || pick.day_low != null) && (
            <div className="layer-row">
              <label>Day H/L</label>
              <span>
                {fmtPrice(pick.day_high)} / {fmtPrice(pick.day_low)}
              </span>
            </div>
          )}
        </div>

        <div className="card-row" style={{ marginTop: 8 }}>
          <span className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>
            {pick.phit != null ? `P(hit) ${(pick.phit * 100).toFixed(0)}%` : "\u00A0"}
          </span>
          <HitBadge hit={pick.target_hit} />
        </div>
      </div>
    </div>
  );
}
