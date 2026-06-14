import type { PickRow } from "@/lib/types";

function fmtPrice(n: number | null) {
  return n == null ? "—" : `$${n.toFixed(2)}`;
}
function fmtChg(n: number | null) {
  if (n == null) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

export default function PickCard({ pick }: { pick: PickRow }) {
  const isBull = pick.direction === "bull";
  const conviction = pick.conviction ?? 0;
  const chgUp = (pick.chg_pct ?? 0) >= 0;

  return (
    <div className={`pick-card ${isBull ? "bull-card" : "bear-card"}`}>
      <div className="card-head">
        <div>
          <div className="card-ticker">{pick.ticker}</div>
          <div className="card-name">{pick.company ?? ""}</div>
        </div>
        <div>
          <div className="card-price">{fmtPrice(pick.price)}</div>
          <div className={`card-chg ${chgUp ? "up" : "down"}`}>{fmtChg(pick.chg_pct)}</div>
        </div>
      </div>

      <div className="card-body">
        <div className="conviction-row">
          <span className="conviction-label">Conviction</span>
          <div className="conviction-bar-bg">
            <div
              className={`conviction-fill ${isBull ? "bull" : "bear"}`}
              style={{ width: `${Math.min(100, Math.max(0, conviction))}%` }}
            />
          </div>
          <span className="conviction-pct">{conviction.toFixed(0)}%</span>
        </div>

        <div className="card-row">
          <span className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>
            #{pick.rank} · score {pick.net_score != null ? (pick.net_score > 0 ? `+${pick.net_score}` : pick.net_score) : "—"}
          </span>
          {pick.grade && <span className="grade-badge">{pick.grade}</span>}
        </div>

        {(pick.fib_target != null || pick.fib_label) && (
          <div className="fib-row">
            <div className="fib-item">
              <label>Fib target</label>
              <span>{fmtPrice(pick.fib_target)}</span>
            </div>
            {pick.fib_label && (
              <div className="fib-item">
                <label>Level</label>
                <span>{pick.fib_label}</span>
              </div>
            )}
            {pick.fib_hit != null && (
              <div className="fib-item">
                <label>1hr hit</label>
                <span className={pick.fib_hit ? "up" : "down"}>
                  {pick.fib_hit ? "Yes" : "No"}
                </span>
              </div>
            )}
          </div>
        )}

        {pick.fib_hit != null && (
          <div className={`fib-hit-badge ${pick.fib_hit ? "hit" : "miss"}`}>
            {pick.fib_hit ? "✓ Target hit" : "✗ Target missed"}
            {pick.fib_window_high != null && pick.fib_window_low != null && (
              <span className="fib-hit-range mono">
                {" "}· hi {fmtPrice(pick.fib_window_high)} / lo {fmtPrice(pick.fib_window_low)}
              </span>
            )}
          </div>
        )}

        {pick.earnings_soon && <div className="earnings-flag">⚠ Earnings &lt; 2 days</div>}
        {pick.mtf_aligned === false && (
          <div className="mtf-badge conflict" style={{ marginTop: 8 }}>
            ⚠ Multi-timeframe conflict
          </div>
        )}
      </div>
    </div>
  );
}
