import { supabase } from "./supabase";
import type {
  MomentumPickRow,
  MomentumDaySummary,
  MomentumScanGroup,
  MomentumHitStats,
} from "./types";

export async function getTodayMomentumPicks(): Promise<MomentumPickRow[]> {
  const { data, error } = await supabase
    .from("v_today_momentum_picks")
    .select("*")
    .order("direction", { ascending: true })
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
    .order("direction", { ascending: true })
    .order("rank", { ascending: true, nullsFirst: false })
    .order("conviction", { ascending: false, nullsFirst: false });
  if (error) throw error;
  return (data ?? []) as MomentumPickRow[];
}

export async function getMomentumDays(): Promise<MomentumDaySummary[]> {
  const { data, error } = await supabase
    .from("momentum_scans")
    .select("trade_date, et_time, n_long, n_short, run_ts")
    .order("run_ts", { ascending: false })
    .limit(500);
  if (error) throw error;

  const map = new Map<string, MomentumDaySummary>();
  for (const row of (data ?? []) as {
    trade_date: string | null;
    et_time: string | null;
    n_long: number | null;
    n_short: number | null;
  }[]) {
    if (!row.trade_date) continue;
    if (!map.has(row.trade_date)) {
      map.set(row.trade_date, {
        trade_date: row.trade_date,
        n_long: row.n_long ?? 0,
        n_short: row.n_short ?? 0,
        et_time: row.et_time ?? "",
      });
    }
  }
  return Array.from(map.values()).sort((a, b) =>
    a.trade_date < b.trade_date ? 1 : -1
  );
}

// Per-day whole-day target hit-rate stats (from v_momentum_hit_stats).
export async function getMomentumHitStats(limit = 60): Promise<MomentumHitStats[]> {
  const { data, error } = await supabase
    .from("v_momentum_hit_stats")
    .select("*")
    .order("trade_date", { ascending: false })
    .limit(limit);
  if (error) throw error;
  return (data ?? []) as MomentumHitStats[];
}

export interface MomentumOverallStats {
  validated: number;
  hits: number;
  hitPct: number | null;
  longValidated: number;
  longHits: number;
  longHitPct: number | null;
  shortValidated: number;
  shortHits: number;
  shortHitPct: number | null;
  days: number;
}

export function aggregateHitStats(rows: MomentumHitStats[]): MomentumOverallStats {
  const acc = rows.reduce(
    (a, r) => {
      a.validated += r.validated ?? 0;
      a.hits += r.hits ?? 0;
      a.longValidated += r.long_validated ?? 0;
      a.longHits += r.long_hits ?? 0;
      a.shortValidated += r.short_validated ?? 0;
      a.shortHits += r.short_hits ?? 0;
      return a;
    },
    {
      validated: 0,
      hits: 0,
      longValidated: 0,
      longHits: 0,
      shortValidated: 0,
      shortHits: 0,
    }
  );
  const pct = (h: number, n: number) => (n > 0 ? (h / n) * 100 : null);
  return {
    validated: acc.validated,
    hits: acc.hits,
    hitPct: pct(acc.hits, acc.validated),
    longValidated: acc.longValidated,
    longHits: acc.longHits,
    longHitPct: pct(acc.longHits, acc.longValidated),
    shortValidated: acc.shortValidated,
    shortHits: acc.shortHits,
    shortHitPct: pct(acc.shortHits, acc.shortValidated),
    days: rows.length,
  };
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
        mode: p.mode ?? null,
        longs: [],
        shorts: [],
      };
      map.set(p.scan_id, g);
    }
    // New model uses `direction`; fall back to legacy `tier` (all long) for old rows.
    const dir = p.direction ?? (p.tier === "TRADE" || p.tier === "WATCH" ? "bull" : null);
    if (dir === "bull") g.longs.push(p);
    else if (dir === "bear") g.shorts.push(p);
  }
  const byRank = (a: MomentumPickRow, b: MomentumPickRow) =>
    (a.rank ?? 999) - (b.rank ?? 999) ||
    (b.conviction ?? 0) - (a.conviction ?? 0);
  for (const g of map.values()) {
    g.longs.sort(byRank);
    g.shorts.sort(byRank);
  }
  return Array.from(map.values()).sort((a, b) => b.et_hour - a.et_hour);
}

export function topMomentumConviction(
  picks: MomentumPickRow[]
): { ticker: string; conviction: number } | null {
  const ranked = picks
    .filter((p) => p.conviction != null)
    .sort((a, b) => (b.conviction ?? 0) - (a.conviction ?? 0));
  if (ranked.length === 0) return null;
  return { ticker: ranked[0].ticker, conviction: ranked[0].conviction ?? 0 };
}
