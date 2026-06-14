import { supabase } from "./supabase";
import type { PickRow, TradeRow, DaySummary, ScanGroup } from "./types";

// All picks for today (ET), ordered for display.
export async function getTodayPicks(): Promise<PickRow[]> {
  const { data, error } = await supabase
    .from("v_today_picks")
    .select("*")
    .order("et_hour", { ascending: false })
    .order("direction", { ascending: true })
    .order("rank", { ascending: true });
  if (error) throw error;
  return (data ?? []) as PickRow[];
}

// All picks for a specific ET day.
export async function getDayPicks(date: string): Promise<PickRow[]> {
  const { data, error } = await supabase
    .from("v_scan_picks")
    .select("*")
    .eq("trade_date", date)
    .order("et_hour", { ascending: false })
    .order("direction", { ascending: true })
    .order("rank", { ascending: true });
  if (error) throw error;
  return (data ?? []) as PickRow[];
}

// Distinct days with a scan count, newest first.
export async function getDays(): Promise<DaySummary[]> {
  const { data, error } = await supabase
    .from("scans")
    .select("trade_date, et_time")
    .order("run_ts", { ascending: false })
    .limit(2000);
  if (error) throw error;

  const map = new Map<string, DaySummary>();
  for (const row of (data ?? []) as { trade_date: string | null; et_time: string | null }[]) {
    if (!row.trade_date) continue;
    const existing = map.get(row.trade_date);
    if (existing) {
      existing.scan_count += 1;
    } else {
      map.set(row.trade_date, {
        trade_date: row.trade_date,
        scan_count: 1,
        last_et_time: row.et_time ?? "",
      });
    }
  }
  return Array.from(map.values()).sort((a, b) =>
    a.trade_date < b.trade_date ? 1 : -1
  );
}

// Most recent trades.
export async function getTrades(limit = 200): Promise<TradeRow[]> {
  const { data, error } = await supabase
    .from("trades")
    .select("*")
    .order("ts", { ascending: false })
    .limit(limit);
  if (error) throw error;
  return (data ?? []) as TradeRow[];
}

// Group a flat pick list into per-scan (per-hour) buckets, newest hour first.
export function groupByScan(picks: PickRow[]): ScanGroup[] {
  const map = new Map<number, ScanGroup>();
  for (const p of picks) {
    let g = map.get(p.scan_id);
    if (!g) {
      g = {
        scan_id: p.scan_id,
        et_time: p.et_time,
        et_hour: p.et_hour,
        session: p.session,
        trade_run: p.trade_run,
        bulls: [],
        bears: [],
      };
      map.set(p.scan_id, g);
    }
    (p.direction === "bull" ? g.bulls : g.bears).push(p);
  }
  return Array.from(map.values()).sort((a, b) => b.et_hour - a.et_hour);
}

// Chart series: highest bullish conviction per scan time, oldest→newest.
export function topConvictionByHour(
  picks: PickRow[]
): { et_time: string; conviction: number }[] {
  const map = new Map<string, number>();
  for (const p of picks) {
    if (p.direction !== "bull" || p.conviction == null) continue;
    const cur = map.get(p.et_time) ?? 0;
    if (p.conviction > cur) map.set(p.et_time, p.conviction);
  }
  return Array.from(map.entries())
    .map(([et_time, conviction]) => ({ et_time, conviction }))
    .sort((a, b) => (a.et_time < b.et_time ? -1 : 1));
}
