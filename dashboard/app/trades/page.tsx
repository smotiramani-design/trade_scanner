import { getTrades } from "@/lib/queries";
import type { TradeRow } from "@/lib/types";

export const revalidate = 60;

function fmt(n: number | null, prefix = "") {
  return n == null ? "—" : `${prefix}${n.toFixed(2)}`;
}

function statusClass(status: string | null) {
  if (status === "executed") return "up";
  if (status === "failed") return "down";
  return "";
}

export default async function TradesPage() {
  let trades: TradeRow[] = [];
  let err: string | null = null;
  try {
    trades = await getTrades();
  } catch (e) {
    err = e instanceof Error ? e.message : String(e);
  }

  return (
    <>
      <div className="topbar">
        <div>
          <div className="page-title">Trades</div>
          <div className="page-sub">Decisions from the 10 AM, 12 PM, and 2 PM ET trade runs</div>
        </div>
      </div>

      {err ? (
        <div className="error-box">Could not load trades: <code>{err}</code></div>
      ) : trades.length === 0 ? (
        <div className="empty-state">
          <div className="icon">💤</div>
          <p>No trades recorded yet.</p>
          <p className="hint">Trades appear once trading runs in a trade window.</p>
        </div>
      ) : (
        <div className="panel" style={{ padding: 0 }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Time</th>
                <th>Ticker</th>
                <th>Action</th>
                <th>Qty</th>
                <th>Entry</th>
                <th>Stop</th>
                <th>Target</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id}>
                  <td className="mono">{t.trade_date ?? "—"}</td>
                  <td className="mono">{t.et_time ?? "—"}</td>
                  <td className="mono">{t.ticker}</td>
                  <td className={t.action === "buy" ? "up" : t.action === "sell" ? "down" : ""}>
                    {t.action ?? "—"}
                  </td>
                  <td className="mono">{t.qty ?? "—"}</td>
                  <td className="mono">{fmt(t.entry_price, "$")}</td>
                  <td className="mono">{fmt(t.stop_loss, "$")}</td>
                  <td className="mono">{fmt(t.take_profit, "$")}</td>
                  <td className={`mono ${statusClass(t.status)}`}>{t.status ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
