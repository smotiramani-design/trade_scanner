import { supabase } from "./supabase";
import type { MomentumPickRow, MomentumDaySummary, MomentumScanGroup } from "./types";

export async function getTodayMomentumPicks(): Promise<MomentumPickRow[]> {
  const { data, error } = await supabase
    .from("v_today_momentum_picks")
    .select("*")
    .order("tier", { ascending: true })
    .order("rank", { ascending: true, nullsFirst: false })
    .order("conviction", { ascending: false, nullsFirst: false });
  if (error) throw error;
  return (data ?? []) as MomentumPickRow[];
}

export async function getMomentumDayPicks(date: string): Promise<MomentumPickRow[]> {
  const { data, error } = await supabase
    .from("v_momentum_picks")
    .select("*")
    .eq("trade_date", date)
    .order("tier", { ascending: true })
    .order("rank", { ascending: true, nullsFirst: false })
    .order("conviction", { ascending: false, nullsFirst: false });
  if (error) throw error;
  return (data ?? []) as MomentumPickRow[];
}

export async function getMomentumDays(): Promise<MomentumDaySummary[]> {
  const { data, error } = await supabase
    .from("momentum_scans")
    .select("trade_date, et_time, n_trade, n_watch")
    .order("run_ts", { ascending: false })
    .limit(500);
  if (error) throw error;

  const map = new Map<string, MomentumDaySummary>();
  for (const row of (data ?? []) as {
    trade_date: string | null;
    et_time: string | null;
    n_trade: number | null;
    n_watch: number | null;
  }[]) {
    if (!row.trade_date) continue;
    if (!map.has(row.trade_date)) {
      map.set(row.trade_date, {
        trade_date: row.trade_date,
        n_trade: row.n_trade ?? 0,
        n_watch: row.n_watch ?? 0,
        et_time: row.et_time ?? "",
      });
    }
  }
  return Array.from(map.values()).sort((a, b) =>
    a.trade_date < b.trade_date ? 1 : -1
  );
}

export function groupMomentumByScan(picks: MomentumPickRow[]): MomentumScanGroup[] {
  const map = new Map<number, MomentumScanGroup>();
  for (const p of picks) {
    let g = map.get(p.scan_id);
    if (!g) {
      g = {
        scan_id: p.scan_id,
        et_time: p.et_time,
        et_hour: p.et_hour,
        session: p.session,
        universe: p.universe,
        trade: [],
        watch: [],
      };
      map.set(p.scan_id, g);
    }
    if (p.tier === "TRADE") g.trade.push(p);
    else if (p.tier === "WATCH") g.watch.push(p);
  }
  for (const g of map.values()) {
    g.trade.sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999));
    g.watch.sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
  }
  return Array.from(map.values()).sort((a, b) => b.et_hour - a.et_hour);
}

export function topMomentumConviction(
  picks: MomentumPickRow[]
): { ticker: string; conviction: number } | null {
  const trade = picks
    .filter((p) => p.tier === "TRADE" && p.conviction != null)
    .sort((a, b) => (b.conviction ?? 0) - (a.conviction ?? 0));
  if (trade.length === 0) return null;
  return { ticker: trade[0].ticker, conviction: trade[0].conviction ?? 0 };
}
