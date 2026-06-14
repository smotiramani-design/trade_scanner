// Row shapes returned by the Supabase views/tables.

export interface PickRow {
  trade_date: string;        // "2026-06-13"
  et_time: string;           // "09:35"
  et_hour: number;
  session: string | null;
  direction: "bull" | "bear";
  rank: number;
  ticker: string;
  company: string | null;
  conviction: number | null;
  grade: string | null;
  net_score: number | null;
  price: number | null;
  chg_pct: number | null;
  fib_target: number | null;
  fib_label: string | null;
  mtf_aligned: boolean | null;
  earnings_soon: boolean | null;
  verdict: string | null;
  universe: string | null;
  trade_run: boolean | null;
  run_ts: string;
  scan_id: number;
}

export interface TradeRow {
  id: number;
  scan_id: number;
  trade_date: string | null;
  et_time: string | null;
  ticker: string;
  action: string | null;
  reason: string | null;
  qty: number | null;
  entry_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  size_usd: number | null;
  order_id: string | null;
  status: string | null;
  dry_run: boolean | null;
  ts: string;
}

export interface DaySummary {
  trade_date: string;
  scan_count: number;
  last_et_time: string;
}

// Picks for one scan (one hour), split by direction.
export interface ScanGroup {
  scan_id: number;
  et_time: string;
  et_hour: number;
  session: string | null;
  trade_run: boolean | null;
  bulls: PickRow[];
  bears: PickRow[];
}
