import type { MomentumPickRow } from "@/lib/types";
import { parseSignalChips } from "@/lib/signals";
import SignalChips from "./SignalChips";

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
  const signalChips = parseSignalChips(pick.signals);
  const nSignals = signalChips.length || 10;
  const keySignals = (() => {
    const raw = pick.key_signals as unknown;
    if (Array.isArray(raw)) return raw.filter((x): x is string => typeof x === "string");
    if (typeof raw === "string") {
      try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          return parsed.filter((x): x is string => typeof x === "string");
        }
      } catch {
        /* ignore */
      }
    }
    return [] as string[];
  })();

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

        <div className="card-row">
          <span className={`tier-badge ${isLong ? "trade" : "skip"}`}>
            {isLong ? "LONG" : "SHORT"}
          </span>
          <span className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>
            {pick.grade ? `${pick.grade} · ` : ""}
            {pick.net_score != null
              ? `score ${pick.net_score > 0 ? "+" : ""}${pick.net_score}/${nSignals}`
              : ""}
          </span>
        </div>

        <SignalChips signals={signalChips} />

        {pick.analysis && (
          <div className="analysis-text">{pick.analysis}</div>
        )}

        {keySignals.length > 0 && (
          <div className="ac-keysig" style={{ marginTop: 6 }}>
            {keySignals.map((k, i) => (
              <span className="keysig-chip" key={i}>
                {k}
              </span>
            ))}
          </div>
        )}

        {(pick.fib_entry != null || pick.fib_stop != null ||
          pick.fib_t1 != null || pick.fib_t2 != null || pick.day_target != null ||
          pick.day_high != null || pick.day_low != null) && (
          <div className="fib-row">
            {pick.fib_entry != null && (
              <div className="fib-item">
                <label>Entry</label>
                <span>{fmtPrice(pick.fib_entry)}</span>
              </div>
            )}
            {pick.fib_stop != null && (
              <div className="fib-item">
                <label>Stop</label>
                <span>{fmtPrice(pick.fib_stop)}</span>
              </div>
            )}
            {(pick.fib_t1 ?? pick.day_target) != null && (
              <div className="fib-item">
                <label>
                  T1
                  {(pick.day_target_label || "")
                    ? ` · ${pick.day_target_label}`
                    : ""}
                </label>
                <span>{fmtPrice(pick.fib_t1 ?? pick.day_target)}</span>
              </div>
            )}
            {pick.fib_t2 != null && (
              <div className="fib-item">
                <label>T2</label>
                <span>{fmtPrice(pick.fib_t2)}</span>
              </div>
            )}
            {pick.day_target != null && (
              <div className="fib-item">
                <label>Day hit</label>
                <span
                  className={
                    pick.target_hit === true
                      ? "up"
                      : pick.target_hit === false
                        ? "down"
                        : undefined
                  }
                  style={
                    pick.target_hit == null
                      ? { color: "var(--muted)" }
                      : undefined
                  }
                >
                  {pick.target_hit === true
                    ? "Yes"
                    : pick.target_hit === false
                      ? "No"
                      : "Pending"}
                </span>
              </div>
            )}
            {pick.day_high != null && (
              <div className="fib-item">
                <label>Day high</label>
                <span>{fmtPrice(pick.day_high)}</span>
              </div>
            )}
            {pick.day_low != null && (
              <div className="fib-item">
                <label>Day low</label>
                <span>{fmtPrice(pick.day_low)}</span>
              </div>
            )}
          </div>
        )}

        <div className="card-row" style={{ marginTop: 8 }}>
          <span className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>
            {pick.phit != null ? `P(hit) ${(pick.phit * 100).toFixed(0)}%` : "\u00A0"}
          </span>
          <HitBadge hit={pick.target_hit} />
        </div>

        {pick.day_target != null && (
          pick.target_hit === true ? (
            <div className="fib-hit-badge hit">✓ Target hit (before stop)</div>
          ) : pick.target_hit === false ? (
            <div className="fib-hit-badge miss">✗ Miss — stop first or no target</div>
          ) : (
            <div className="fib-hit-badge pending">
              ◷ Hit check pending — runs at 4 PM ET
            </div>
          )
        )}
      </div>
    </div>
  );
}
