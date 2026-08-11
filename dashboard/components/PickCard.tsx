import type { PickRow } from "@/lib/types";
import { parseSignalChips } from "@/lib/signals";
import SignalChips from "./SignalChips";

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
  const signalChips = parseSignalChips(pick.signals);
  const nSignals = signalChips.length || 10;

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
            #{pick.rank} · score{" "}
            {pick.net_score != null
              ? `${pick.net_score > 0 ? "+" : ""}${pick.net_score}/${nSignals}`
              : "—"}
          </span>
          {pick.grade && <span className="grade-badge">{pick.grade}</span>}
        </div>

        {pick.verdict && (
          <div className="verdict-line">{pick.verdict}</div>
        )}

        <SignalChips signals={signalChips} />

        {pick.analysis && (
          <div className="analysis-text">{pick.analysis}</div>
        )}

        {pick.conflicting && pick.conflicting.length > 0 && (
          <div className="conflict-flag">
            ⚠ Conflicting: {pick.conflicting.join(", ")}
          </div>
        )}

        {(pick.fib_entry != null || pick.fib_stop != null ||
          pick.fib_t1 != null || pick.fib_t2 != null || pick.fib_target != null) && (
          <div className="fib-row">
            {pick.fib_entry != null && (
              <div className="fib-item">
                <label>Fib entry</label>
                <span>{fmtPrice(pick.fib_entry)}</span>
              </div>
            )}
            {pick.fib_stop != null && (
              <div className="fib-item">
                <label>Fib stop</label>
                <span>{fmtPrice(pick.fib_stop)}</span>
              </div>
            )}
            {(pick.fib_t1 ?? pick.fib_target) != null && (
              <div className="fib-item">
                <label>Fib T1{pick.fib_label ? ` · ${pick.fib_label}` : ""}</label>
                <span>{fmtPrice(pick.fib_t1 ?? pick.fib_target)}</span>
              </div>
            )}
            {pick.fib_t2 != null && (
              <div className="fib-item">
                <label>Fib T2</label>
                <span>{fmtPrice(pick.fib_t2)}</span>
              </div>
            )}
            {pick.fib_target != null && (
              <div className="fib-item">
                <label>1hr hit</label>
                <span className={pick.fib_hit === true ? "up" : pick.fib_hit === false ? "down" : undefined}
                      style={pick.fib_hit == null ? { color: "var(--muted)" } : undefined}>
                  {pick.fib_hit === true ? "Yes" : pick.fib_hit === false ? "No" : "Pending"}
                </span>
              </div>
            )}
          </div>
        )}

        {(pick.atr_entry != null || pick.atr_stop != null ||
          pick.atr_t1 != null || pick.atr_t2 != null) && (
          <div className="fib-row" style={{ marginTop: 4 }}>
            {pick.atr_entry != null && (
              <div className="fib-item">
                <label>ATR entry</label>
                <span>{fmtPrice(pick.atr_entry)}</span>
              </div>
            )}
            {pick.atr_stop != null && (
              <div className="fib-item">
                <label>ATR stop</label>
                <span>{fmtPrice(pick.atr_stop)}</span>
              </div>
            )}
            {pick.atr_t1 != null && (
              <div className="fib-item">
                <label>ATR T1 · 1R</label>
                <span>{fmtPrice(pick.atr_t1)}</span>
              </div>
            )}
            {pick.atr_t2 != null && (
              <div className="fib-item">
                <label>ATR T2 · 2R</label>
                <span>{fmtPrice(pick.atr_t2)}</span>
              </div>
            )}
          </div>
        )}

        {(pick.pred_lo != null || pick.pred_mid != null || pick.pred_hi != null) && (
          <div className="fib-row" style={{ marginTop: 4 }}>
            {pick.pred_lo != null && (
              <div className="fib-item">
                <label>Pred lo</label>
                <span>{fmtPrice(pick.pred_lo)}</span>
              </div>
            )}
            {pick.pred_mid != null && (
              <div className="fib-item">
                <label>Pred mid{pick.pred_mid_pct != null ? ` · ${pick.pred_mid_pct.toFixed(1)}%` : ""}</label>
                <span>{fmtPrice(pick.pred_mid)}</span>
              </div>
            )}
            {pick.pred_hi != null && (
              <div className="fib-item">
                <label>Pred hi</label>
                <span>{fmtPrice(pick.pred_hi)}</span>
              </div>
            )}
            {pick.ens_phit != null ? (
              <div className="fib-item">
                <label>Ens P(hit)</label>
                <span>{(pick.ens_phit * 100).toFixed(0)}%</span>
              </div>
            ) : pick.xgb_phit != null ? (
              <div className="fib-item">
                <label>Boosted P(hit)</label>
                <span>{(pick.xgb_phit * 100).toFixed(0)}%</span>
              </div>
            ) : null}
          </div>
        )}

        {(pick.adv_mid != null || pick.ev_score != null) && (
          <div className="fib-row" style={{ marginTop: 4 }}>
            {pick.adv_mid != null && (
              <div className="fib-item">
                <label>Risk mid{pick.adv_mid_pct != null ? ` · ${pick.adv_mid_pct.toFixed(1)}%` : ""}</label>
                <span>{fmtPrice(pick.adv_mid)}</span>
              </div>
            )}
            {pick.ev_score != null && (
              <div className="fib-item">
                <label>EV score</label>
                <span className={pick.ev_score >= 0 ? "up" : "down"}>
                  {pick.ev_score >= 0 ? "+" : ""}
                  {pick.ev_score.toFixed(1)}%
                </span>
              </div>
            )}
          </div>
        )}

        {pick.fib_target != null && (
          pick.fib_hit === true ? (
          <div className="fib-hit-badge hit">✓ Target hit (before stop)</div>
          ) : pick.fib_hit === false ? (
          <div className="fib-hit-badge miss">✗ Miss — stop first or no target</div>
          ) : (
          <div className="fib-hit-badge pending">
            ◷ Hit check pending — runs after the 1hr window
          </div>
          )
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
