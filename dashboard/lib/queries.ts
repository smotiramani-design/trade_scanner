import { supabase } from "./supabase";
import type { PickRow, TradeRow, DaySummary, ScanGroup, FibHitStats } from "./types";

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

/** ET calendar date as YYYY-MM-DD. */
export function getEtTodayDateString(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
}

/** True after 4 PM ET on tradeDate; always true for prior ET days. */
export function isPastFibValidationTime(tradeDate: string): boolean {
  const today = getEtTodayDateString();
  if (tradeDate < today) return true;
  if (tradeDate > today) return false;

  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "numeric",
    hour12: false,
  }).formatToParts(new Date());
  const hour = Number(parts.find((p) => p.type === "hour")?.value ?? 0);
  return hour >= 16;
}

/** Aggregate fib_hit results for one ET day (reads picks table). */
export async function getFibHitStats(tradeDate: string): Promise<FibHitStats | null> {
  const { data, error } = await supabase
    .from("picks")
    .select("fib_hit, fib_target, fib_validated_at")
    .eq("trade_date", tradeDate)
    .not("fib_target", "is", null);
  if (error) throw error;

  const rows = (data ?? []) as {
    fib_hit: boolean | null;
    fib_target: number | null;
    fib_validated_at: string | null;
  }[];

  if (rows.length === 0) return null;

  let hits = 0;
  let misses = 0;
  let unknown = 0;
  for (const row of rows) {
    if (row.fib_validated_at == null) continue;
    if (row.fib_hit === true) hits += 1;
    else if (row.fib_hit === false) misses += 1;
    else unknown += 1;
  }

  const validated = hits + misses + unknown;
  if (validated === 0) return null;

  return {
    hits,
    misses,
    unknown,
    validated,
    with_target: rows.length,
    hit_pct: Math.round((hits / validated) * 100),
  };
}
